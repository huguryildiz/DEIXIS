import type { ReviewNotReviewed } from '../api'
import { notReviewedText } from '../labels'
import { t } from '../i18n'

export function NotReviewed({ rows, sectionLabel }: { rows: ReviewNotReviewed[]; sectionLabel: (ref: string) => string }) {
  return <ul className="review-coverage">{rows.map((row, i) => <li key={i}><span data-stored-text>{row.claim_ref}{row.section_ref && ` · ${sectionLabel(row.section_ref)}`}</span> · {notReviewedText(row.reason)}{row.request_chars != null && ` · ${t(row.request_chars === 1 ? '{n} character' : '{n} characters', { n: row.request_chars })}`}</li>)}</ul>
}
