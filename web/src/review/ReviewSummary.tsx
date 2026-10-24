import type { ReviewCard } from '../api'
import { t } from '../i18n'
import './review.css'

export function ReviewSummary({ reviews, open }: { reviews: ReviewCard[]; open: () => void }) {
  if (!reviews.length) return null
  const findings = reviews.reduce((sum, review) => sum + review.open_finding_count, 0)
  return <button type="button" className="review-target-line" onClick={open}>{t('Reviewed by another model: {reviews}, {findings}', {
    reviews: t(reviews.length === 1 ? '{n} review' : '{n} reviews', { n: reviews.length }),
    findings: t(findings === 1 ? '{n} open finding' : '{n} open findings', { n: findings }),
  })}</button>
}
