import { useId } from 'react'
import { ChevronDown, ChevronRight, CircleX, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ReportDetail } from '../api'
import { t, uiLocale } from '../i18n'
import { checkCounts, editRuleLabel, notCheckedLabel, skippedReasonLabel, skippedRuleLabel } from './editLabels'

export function EditCheckPanel({ report, finished, busy, checking, labels, onCheck }: {
  report: ReportDetail; finished: boolean; busy: boolean; checking: boolean
  labels: (id: string) => string; onCheck: () => void
}) {
  const reasonId = useId()
  if (!report.has_human_edits) return null
  const check = report.edit_check
  const prefix = report.edited_after_version === null ? t('Edited by hand') : t('Edited by hand after version {n}', { n: report.edited_after_version })
  const date = check ? new Date(check.created_at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) : ''
  const sentence = !check
    ? report.edited_after_version === null ? t('Edited by hand; edited text was not checked again.')
      : t('Edited by hand after version {n}; edited text was not checked again.', { n: report.edited_after_version })
    : check.current
      ? t('{prefix}; the edited text was checked by code rules ({date}): {errors}, {warnings}; whether the cited evidence supports each sentence was not checked.', { prefix, date, ...checkCounts(check.errors, check.warnings) })
      : t('{prefix}; the last check ({date}) does not cover the current inputs; whether the cited evidence supports each sentence was not checked.', { prefix, date })
  const reason = !finished || report.status === 'in_progress' ? t('A report can be checked once its run has finished.')
    : busy ? t(checking ? 'Checking…' : 'An operation is in progress.')
    : check?.current ? t('This check covers the current text and citations.') : ''
  return <section className="evidence-report-edit-check" aria-label={t('Edited text check')}>
    <div className="evidence-report-check-sentence"><p role="status">{sentence}</p>{check && <span>{t(check.current ? 'Current' : 'Out of date')}</span>}</div>
    <div className="evidence-report-check-action"><Button size="sm" variant="outline" disabled={Boolean(reason)} aria-busy={checking} aria-describedby={reason ? reasonId : undefined} onClick={onCheck}>{t(checking ? 'Checking…' : check ? 'Check again' : 'Check edited text')}</Button>{reason && <p id={reasonId}>{reason}</p>}</div>
    {check && <>
      {!check.current && <p>{t('This is an earlier check; edits or other inputs changed since.')}</p>}
      {check.items.length ? <ol className="evidence-report-check-items">{check.items.map((item, i) => {
        const Icon = item.severity === 'error' ? CircleX : TriangleAlert
        const detail = item.detail.startsWith('ERROR: ') ? item.detail.slice(7) : item.detail.startsWith('WARNING: ') ? item.detail.slice(9) : item.detail
        return <li key={i}><span className={`evidence-report-check-severity is-${item.severity}`}><Icon size={14} aria-hidden />{t(item.severity === 'error' ? 'Error' : 'Warning')}</span> · {item.section_id ? labels(item.section_id) : t('Report')} · {editRuleLabel(item.rule)}<p data-stored-text>{detail}</p></li>
      })}</ol> : <p>{t('The rules that ran reported no error or warning.')}</p>}
      <details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Rules that ran ({n})', { n: check.rules_run.length })}</summary><ul>{check.rules_run.map((rule, i) => <li key={i} data-stored-text>{rule.replaceAll('_', ' ')}</li>)}</ul></details>
      {check.skipped_rules.length > 0 && <details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Rules that did not run for some claims ({n})', { n: check.skipped_rules.length })}</summary><ul>{check.skipped_rules.map((item, i) => <li key={i}><span data-stored-text>{item.claim_key}</span> · {item.section_id ? labels(item.section_id) : t('Report')} · {skippedRuleLabel(item.rule)}: {skippedReasonLabel(item.reason)}</li>)}</ul></details>}
      <p className="evidence-report-fine">{t('Not checked: {items}.', { items: check.not_checked.map(notCheckedLabel).join(', ') })}</p>
    </>}
  </section>
}
