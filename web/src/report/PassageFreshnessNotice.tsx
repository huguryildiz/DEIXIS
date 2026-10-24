import type { PassageFreshness } from '../api'
import { t } from '../i18n'
import { Notice } from '../Notice'

export function PassageFreshnessNotice({ freshness }: { freshness: PassageFreshness | undefined }) {
  if (!freshness) return null
  const count = (status: string) => freshness.affected.filter(item => item.evidence_status === status).length
  const a = count('text_superseded'), b = count('pdf_replaced'), c = count('pdf_removed'), k = freshness.unresolved.length
  const parts = [
    a ? t(a === 1 ? '{n} passage this report used is no longer the current text of its PDF' : '{n} passages this report used are no longer the current text of their PDF', { n: a }) : '',
    b ? t(b === 1 ? '{n} comes from a replaced PDF' : '{n} come from a replaced PDF', { n: b }) : '',
    c ? t(c === 1 ? '{n} comes from a removed PDF' : '{n} come from a removed PDF', { n: c }) : '',
  ].filter(Boolean)
  const n = freshness.file_restored_after.length
  return <>
    {(freshness.affected.length > 0 || k > 0) && <Notice tone="attention">{t('Passage freshness compared:')} {parts.join(', ')}{k > 0 && `${parts.length ? '; ' : ''}${t(k === 1 ? '{n} reference could not be resolved' : '{n} references could not be resolved', { n: k })}`}. {t('Semantic support not checked.')}</Notice>}
    {n > 0 && <Notice tone="info">{t(n === 1
      ? '{n} passage this report used was extracted before its PDF file was restored. The restored file is not necessarily the bytes it was read from.'
      : '{n} passages this report used were extracted before their PDF file was restored. The restored file is not necessarily the bytes they were read from.', { n })}</Notice>}
  </>
}
