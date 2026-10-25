import type { ReviewNotReviewed } from '../lib/api'
import { notReviewedText } from '../lib/labels'
import { t } from '../lib/i18n'

export function NotReviewed({ rows, sectionLabel, sourceName }: { rows: ReviewNotReviewed[]; sourceName?: (id: string) => string; sectionLabel: (ref: string) => string }) {
  return <ul className="review-coverage">{rows.map((row, i) => <li key={i}><span data-stored-text>{row.source_id ? sourceName?.(row.source_id) ?? t('an item no longer in the review copy') : row.claim_ref}{row.section_ref && ` · ${sectionLabel(row.section_ref)}`}</span> · {notReviewedText(row.reason)}{row.request_chars != null && ` · ${t(row.request_chars === 1 ? '{n} character' : '{n} characters', { n: row.request_chars })}`}</li>)}</ul>
}
