import { FileText } from 'lucide-react'
import type { ReviewEvidence as Evidence } from '../api'
import { MathText } from '../MathText'
import { t } from '../i18n'

// A located quote (mockup `.finding .quote` and `.loc`): code found the text in the stored passage; whether it supports
// the target was not checked. "Open in source" shows the passage with the quote marked.
export function ReviewEvidence({ evidence, sourceName, open }: { evidence: Evidence[]; sourceName: (id: string) => string; open: (id: string, anchor: string) => void }) {
  return <div className="review-evidence">{evidence.map((item, i) => <div key={i}>
    <blockquote className="quote" data-stored-text><mark><MathText text={item.anchor_text} /></mark></blockquote>
    <p className="loc"><span data-stored-text>{sourceName(item.source_version_id)}</span><span aria-hidden>·</span><span>{t('Located in the passage')}{item.anchor_match === 'normalized' && <> · {t('after normalising spacing and case')}</>}</span><span aria-hidden>·</span><span>{t('Whether it supports the target was not checked.')}</span></p>
    <div className="rowacts"><button type="button" className="review-source-link" onClick={() => open(item.passage_id, item.anchor_text)}><FileText aria-hidden />{t('Open in source')}</button></div>
  </div>)}</div>
}
