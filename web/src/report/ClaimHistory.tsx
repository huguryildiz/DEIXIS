import { useId } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ReportClaim } from '../api'
import { t, uiLocale } from '../i18n'
import { reportRevisionLabels } from '../labels'
import { citationCount } from './editLabels'

export function ClaimHistory({ claim, createdAt, busy, restore }: {
  claim: ReportClaim; createdAt: string; busy: boolean; restore: (from: string) => void
}) {
  const descriptionId = useId(), busyId = useId()
  if (!claim.revisions.length) return null
  const control = (from: string) => <Button variant="ghost" size="sm" disabled={busy} aria-describedby={`${descriptionId}${busy ? ` ${busyId}` : ''}`} onClick={() => restore(from)}>{t('Restore')}</Button>
  return <details className="evidence-report-history">
    <summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('History ({n})', { n: claim.revisions.length })}</summary>
    <span className="sr-only" id={descriptionId}>{t("Restore this version's text and citations")}</span>
    {busy && <p id={busyId}>{t('An operation is in progress.')}</p>}
    <ol><li><span>{t('Model text')} · {new Date(createdAt).toLocaleDateString(uiLocale())} · {citationCount(claim.original_evidence_count)}</span><p data-stored-text>{claim.model_text}</p>{(claim.text !== claim.model_text || claim.removed_links.length > 0) && control('model')}</li>
      {claim.revisions.map((item, i) => {
        const count = item.link_count ?? claim.original_evidence_count
        const previous = i === 0 ? claim.original_evidence_count : claim.revisions[i - 1].link_count ?? claim.original_evidence_count
        return <li key={item.id}><span>{t(reportRevisionLabels[item.kind] ?? item.kind)} · {new Date(item.created_at).toLocaleDateString(uiLocale())} · {count !== previous ? t('Citations: from {from} to {to}', { from: previous, to: count }) : citationCount(count)}{item.note && <> · <span data-stored-text>{item.note}</span></>}</span><p data-stored-text>{item.text}</p>{item.changes_current && control(item.id)}</li>
      })}
    </ol>
  </details>
}
