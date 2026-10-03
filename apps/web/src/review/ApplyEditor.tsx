import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type ReportClaim, type ReportDetail, type ReviewFindingRow } from '../api'
import { ClaimEdit, type ClaimEditBody } from '../report/ClaimEdit'
import { MathText } from '../MathText'
import { reviewFindingLabels } from '../labels'
import { useToast } from '../Toast'
import { t } from '../i18n'
import { newCommand, pendingCommand, useWriteCommand } from './commands'
import { RetryNotice } from './RetryNotice'

export function ApplyEditor({ researchId, reportId, reviewId, finding, claim: original, sourceName, cancel, saved, refreshed }: {
  researchId: string; reportId: string; reviewId: string; finding: ReviewFindingRow; claim: ReportClaim
  sourceName: (id: string) => string; cancel: () => void; saved: (report: ReportDetail) => void | Promise<void>; refreshed: (report: ReportDetail) => void
}) {
  const identity = `${researchId}:${reviewId}:${finding.id}:apply`
  const previous = pendingCommand(identity)
  const previousBody = previous ? JSON.parse(previous.body) as { text?: string; note?: string } : null
  const key = useRef(previous?.key ?? crypto.randomUUID())
  const [claim, setClaim] = useState(original)
  const [fingerprint, setFingerprint] = useState(finding.dependency_fingerprint)
  const [conflicts, setConflicts] = useState(0)
  const [error, setError] = useState('')
  const [dependenciesChanged, setDependenciesChanged] = useState(false)
  const [reading, setReading] = useState(false)
  const toast = useToast()
  const readCurrent = async () => {
    const [review, report] = await Promise.all([api.review(researchId, reviewId), api.report(researchId, reportId)])
    const row = review.findings.find(f => f.id === finding.id)
    const live = report.sections.flatMap(s => s.claims).find(c => c.id === original.id)
    if (!row?.dependency_fingerprint || !live) throw new Error(t('The claim is no longer available in this report.'))
    return { row, report, live }
  }
  const command = useWriteCommand(identity, c => api.applyReview(researchId, reviewId, finding.id, c.body, c.key), async result => {
    key.current = crypto.randomUUID()
    toast('success', [t('Saved through the editor. The finding is recorded as accepted with this revision.'), finding.finding.suggested_fix !== null ? t(result.applied_matches_suggestion ? 'The saved text matches the suggestion.' : 'The saved text differs from the suggestion.') : ''].filter(Boolean).join(' '))
    try { await saved(await api.report(researchId, reportId)) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setDependenciesChanged(true) }
  }, async e => {
    key.current = crypto.randomUUID()
    if (e.code === 'dependencies_changed') { setError(e.message); setDependenciesChanged(true); return }
    if (e.status === 409) {
      toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message }))
      try { const next = await readCurrent(); setClaim(next.live); setFingerprint(next.row.dependency_fingerprint); setConflicts(n => n + 1); refreshed(next.report) }
      catch (readError) { setError(readError instanceof Error ? readError.message : String(readError)) }
    } else setError(e.message)
  })
  const reopen = async () => {
    if (reading || command.pending) return
    setReading(true)
    try {
      const next = await readCurrent()
      setClaim(next.live); setFingerprint(next.row.dependency_fingerprint); setConflicts(n => n + 1)
      setError(''); setDependenciesChanged(false); key.current = crypto.randomUUID(); refreshed(next.report)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setReading(false) }
  }
  const save = (body: ClaimEditBody, expectedVersion: number) => {
    if (command.pending || dependenciesChanged) return
    void command.send(newCommand({ text: body.text ?? null, link_ids: body.link_ids ?? null, note: body.note?.trim() || null, expected_version: expectedVersion, dependency_fingerprint: fingerprint }, key.current))
  }
  return <div className="review-apply-editor">
    <ClaimEdit claim={claim} initialText={previousBody?.text ?? finding.finding.suggested_fix ?? claim.text} conflicts={conflicts} sourceName={sourceName} cancel={cancel} save={save} busy={Boolean(command.pending) || reading || dependenciesChanged} locked={Boolean(command.pending)} error={error} context={<div className="review-editor-context"><p>{t('From review finding · {kind}', { kind: t(reviewFindingLabels[finding.finding.kind]) })}</p><h4>{t('Text at review time')}</h4><p className="review-claim" data-stored-text><MathText text={finding.finding.target.text_at_snapshot ?? ''} /></p>{finding.finding.target.text_at_snapshot !== claim.text && <><h4>{t('Current text')}</h4><p className="review-claim" data-stored-text><MathText text={claim.text} /></p></>}</div>} />
    {dependenciesChanged && <Button type="button" size="sm" variant="outline" disabled={reading} aria-describedby={reading ? 'review-editor-reading' : undefined} onClick={() => void reopen()}>{t('Reopen with current text')}</Button>}
    {reading && <p id="review-editor-reading" role="status">{t('Loading current text…')}</p>}
    {command.pending && !command.busy && <RetryNotice busy={command.busy} retry={() => void command.retry()} />}
  </div>
}
