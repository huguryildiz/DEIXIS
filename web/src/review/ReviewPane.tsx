import { useCallback, useEffect, useRef, useState } from 'react'
import { CircleX } from 'lucide-react'
import { api, type ReviewDetail as Detail, type Source, type ReviewTargetKind } from '../lib/api'
import { ModelName } from '../components/ModelName'
import { useModelText } from '../lib/modelText'
import { runStatusLabels } from '../lib/labels'
import { t, uiLocale } from '../lib/i18n'
import { useReviewList } from './useReviewList'
import { ReviewDetail } from './ReviewDetail'

// The review panel's body (mockup `reviewPanel`): the reviews of this target when there is more than one, then the
// chosen review (the newest unless one was opened by name).
export function ReviewPane({ researchId, targetKind, targetId, eventCursor, initial, sources, sectionLabel, open, changed, apply }: {
  researchId: string; targetKind: ReviewTargetKind; targetId: string; eventCursor: number; initial: string | null
  sources: Source[]; sectionLabel: (ref: string) => string; open: (id: string, anchor: string, review?: Detail) => void
  changed: () => void | Promise<void>; apply?: (reviewId: string, findingId: string) => Promise<void>
}) {
  const { reviews, error: listError, refresh: refreshList } = useReviewList(researchId, targetKind, targetId, eventCursor)
  const [selected, setSelected] = useState<string | null>(initial)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState('')
  const sequence = useRef(0)
  const modelText = useModelText()
  const selectedId = selected ?? reviews[0]?.id
  const read = useCallback(async () => {
    if (!selectedId) return
    const ticket = ++sequence.current
    try { const next = await api.review(researchId, selectedId); if (ticket === sequence.current) { setDetail(next); setError('') } }
    catch (e) { if (ticket === sequence.current) setError(e instanceof Error ? e.message : String(e)) }
  }, [researchId, selectedId])
  useEffect(() => { const ref = sequence; void Promise.resolve().then(read); return () => { ref.current++ } }, [read, eventCursor])
  const refresh = async () => { await refreshList(); await read(); await changed() }
  const failure = error || listError
  return <div className="review-pane mk pad detail">
    {failure && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{failure}</span></div>}
    {reviews.length > 1 && <><h4 className="sub">{t('Reviews ({n})', { n: reviews.length })}</h4><div className="review-list" aria-label={t('Reviews')}>{reviews.map(review => <button type="button" className="review-list-row" key={review.id} aria-pressed={selectedId === review.id} onClick={() => setSelected(review.id)}>
      <b>{t(review.state === 'partial' ? 'Partial' : runStatusLabels[review.state])}</b><ModelName connection={review.requested_model.connection} text={modelText(review.requested_model.model)} />
      <time>{new Date(review.created_at).toLocaleString(uiLocale())}</time><span>{t(review.finding_count === 1 ? '{n} finding · {m} open' : '{n} findings · {m} open', { n: review.finding_count, m: review.open_finding_count })}</span>
    </button>)}</div></>}
    {!selectedId ? <p className="foot-note">{t('No review by another model is recorded for this target.')}</p>
      : detail?.id === selectedId ? <ReviewDetail researchId={researchId} review={detail} sources={sources} sectionLabel={sectionLabel} open={(id, anchor) => open(id, anchor, detail)} refresh={refresh} apply={apply} />
        : !failure && <p role="status" className="foot-note"><span className="shimmer-text">{t('Loading review…')}</span></p>}
  </div>
}
