import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type ReviewDetail as Detail, type Source } from '../api'
import { ModelName } from '../ModelName'
import { useModelText } from '../modelText'
import { Notice } from '../Notice'
import { runStatusLabels } from '../labels'
import { t, uiLocale } from '../i18n'
import { useReviewList } from './useReviewList'
import { ReviewDetail } from './ReviewDetail'
import { ReviewRequest } from './ReviewRequest'
import './review.css'

export function ReviewPane({ researchId, targetKind, targetId, version, eventCursor, runActive, unavailableReason = '', sources, sectionLabel, showRequest = false, open, changed, apply }: {
  researchId: string; targetKind: 'answer' | 'report'; targetId: string; version: number; eventCursor: number; runActive: boolean
  unavailableReason?: string; sources: Source[]; sectionLabel: (ref: string) => string; showRequest?: boolean; open: (id: string, anchor: string) => void
  changed: () => void | Promise<void>; apply?: (reviewId: string, findingId: string) => Promise<void>
}) {
  const { reviews, error: listError, refresh: refreshList } = useReviewList(researchId, targetKind, targetId, eventCursor)
  const [selected, setSelected] = useState<string | null>(null)
  const [request, setRequest] = useState(showRequest)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState('')
  const heading = useRef<HTMLHeadingElement>(null), sequence = useRef(0)
  const modelText = useModelText()
  const selectedId = selected ?? reviews[0]?.id
  const read = useCallback(async () => {
    if (!selectedId || request) return
    const ticket = ++sequence.current
    try { const next = await api.review(researchId, selectedId); if (ticket === sequence.current) { setDetail(next); setError('') } }
    catch (e) { if (ticket === sequence.current) setError(e instanceof Error ? e.message : String(e)) }
  }, [researchId, selectedId, request])
  useEffect(() => { const ref = sequence; void Promise.resolve().then(read); return () => { ref.current++ } }, [read, eventCursor])
  useEffect(() => { const frame = requestAnimationFrame(() => heading.current?.focus({ preventScroll: true })); return () => cancelAnimationFrame(frame) }, [])
  const refresh = async () => { await refreshList(); await read(); await changed() }
  return <div className="review-pane">
    <header><h2 ref={heading} tabIndex={-1}>{t('Review by another model')}</h2><p className="review-muted">{t(detail?.assessment_notice ?? 'This is an assessment by a model. It is not peer review and not independent verification.')}</p></header>
    {(error || listError) && <Notice tone="error">{error || listError}</Notice>}
    {reviews.length === 0 ? <p className="review-muted">{t('No review by another model is recorded for this target.')}</p> : <div className="review-list" aria-label={t('Reviews')}>{reviews.map(review => <button type="button" className="review-list-row" key={review.id} aria-pressed={!request && selectedId === review.id} onClick={() => { setSelected(review.id); setRequest(false) }}><span>{t(review.state === 'partial' ? 'Partial' : runStatusLabels[review.state])}</span><ModelName connection={review.requested_model.connection} text={modelText(review.requested_model.model)} /><time>{new Date(review.created_at).toLocaleString(uiLocale())}</time><span>{t(review.finding_count === 1 ? '{n} finding · {m} open' : '{n} findings · {m} open', { n: review.finding_count, m: review.open_finding_count })}</span></button>)}</div>}
    <Button type="button" variant="ghost" size="sm" disabled={Boolean(unavailableReason)} aria-describedby={unavailableReason ? `review-unavailable-${targetId}` : undefined} onClick={() => setRequest(true)}>{t('Review with another model')}</Button>
    {unavailableReason && <p id={`review-unavailable-${targetId}`}>{unavailableReason}</p>}
    {request ? <ReviewRequest researchId={researchId} targetKind={targetKind} targetId={targetId} version={version} runActive={runActive} unavailableReason={unavailableReason} sectionLabel={sectionLabel} started={async id => { setSelected(id); setRequest(false); await refreshList(); await changed() }} /> : selectedId && detail?.id === selectedId ? <ReviewDetail researchId={researchId} review={detail} sources={sources} sectionLabel={sectionLabel} open={open} refresh={refresh} apply={apply} /> : selectedId ? <p role="status">{t('Loading review…')}</p> : null}
  </div>
}
