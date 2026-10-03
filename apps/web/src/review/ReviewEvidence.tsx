import type { ReviewEvidence as Evidence } from '../api'
import { MathText } from '../MathText'
import { t } from '../i18n'

export function ReviewEvidence({ evidence, sourceName, open }: { evidence: Evidence[]; sourceName: (id: string) => string; open: (id: string, anchor: string) => void }) {
  return <div className="review-evidence">{evidence.map((item, i) => <div key={i}><blockquote data-stored-text><MathText text={item.anchor_text} /></blockquote><p>{t('Located in the passage')} · <span data-stored-text>{sourceName(item.source_version_id)}</span>{item.anchor_match === 'normalized' && <> · {t('after normalising spacing and case')}</>}</p><button type="button" className="review-source-link" onClick={() => open(item.passage_id, item.anchor_text)}>{t('Open in source')}</button></div>)}</div>
}
