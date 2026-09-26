import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, ApiError, type AuditAbstractRow, type AuditAnswer, type AuditRow, type AuditRowView, type AuditView } from './api'
import { auditStratumLabels, pageLocator, queueAnswerLabels, queueAnsweredText, versionText, versionTones } from './labels'
import { Notice } from './Notice'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'

// The audit sample of an sw research (slice 20, decisions 5–7). A few works code or the model runs decided without
// asking the person, drawn by a fixed digest. F1 / F2 are answered here; A1 / A2 are for viewing and a manual choice
// from the sources only. The current sample and the earlier answers are shown apart, and no rate is drawn from either.

const ANSWERS: AuditAnswer[] = ['include', 'criterion_not_met', 'not_sure', 'pdf_wrong']
const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)

export function AuditSample({ researchId, lastEvent, onChanged, onOpenSource, onShowInSources }: {
  researchId: string; lastEvent: number; onChanged: () => Promise<void>; onOpenSource: (sourceVersionId: string) => void
  onShowInSources: (workId: string) => void
}) {
  const toast = useToast()
  const [audit, setAudit] = useState<AuditView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => api.audit(researchId).then(next => { setAudit(next); setError('') },
    e => setError(e instanceof Error ? e.message : String(e))), [researchId])
  useEffect(() => { void load() }, [load, lastEvent])

  const act = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true)
    try { await work(); toast('success', done); await load(); await onChanged() }
    catch (e) {
      if (e instanceof ApiError && e.status === 409) toast('error', t('This audit row changed after it was shown; its current state is loaded. Nothing was saved.'))
      else toast('error', e instanceof Error ? e.message : String(e))
      await load()
    } finally { setBusy(false) }
  }
  if (error && !audit) return <Notice tone="error">{t('Could not load the audit sample: {error}', { error })}</Notice>
  if (!audit) return null

  return <section className="audit-panel" aria-labelledby="audit-heading">
    <h3 id="audit-heading">{t('Audit sample')}</h3>
    <p className="queue-muted">{t('A few works that code or the model runs decided without asking you, drawn by a fixed digest ({n} per group). A later reading can change the sample. The counts are counts, not rates.', { n: audit.per_stratum })}</p>
    {(['F1', 'F2'] as const).map(stratum => {
      const group = audit.fulltext[stratum]
      return <div key={stratum} className="audit-group">
        <p className="audit-group-head">{t(auditStratumLabels[stratum])} <small>{t('works in this group: {n}', { n: count(group.size) })}</small></p>
        {group.sample_size > 0
          ? <p className="audit-result">{t('Current sample: you looked at {answered} of {n} rows; you decided differently in {differs}.', { answered: count(group.answered), n: count(group.sample_size), differs: count(group.differs) })}</p>
          : <p className="empty-inline">{t('No work is in this group.')}</p>}
        <ul className="audit-rows">{group.rows.map(row => <AuditRowItem key={row.work_id} researchId={researchId} row={row} busy={busy}
          onOpen={() => onOpenSource(row.source_version_id)}
          onAnswer={answer => act(() => api.answerAuditRow(researchId, row.source_version_id, answer, row.audit_token), t('Your audit answer is recorded as your decision.'))}
          onUndo={() => act(() => api.undoAuditDecision(researchId, row.source_version_id, row.audit_token), t('Your audit answer was taken back.'))} />)}</ul>
      </div>
    })}
    {audit.earlier.length > 0 && <details className="queue-decided audit-earlier">
      <summary><ChevronRight size={14} aria-hidden className="queue-decided-chevron" />{t('Earlier audit answers ({n})', { n: audit.earlier.length })}</summary>
      <p className="queue-muted">{(['F1', 'F2'] as const).map(stratum => t('{group}: {n} answers, {differs} different from the runs', { group: t(auditStratumLabels[stratum]), n: audit.earlier_counts[stratum].answers, differs: audit.earlier_counts[stratum].differs })).join(' · ')}</p>
      <ul>{audit.earlier.map(entry => <li key={entry.work_id}><div>
        <button type="button" className="queue-decided-title" onClick={() => onOpenSource(entry.source_version_id)}>{entry.title}</button>
        <p className="queue-muted">{[t(queueAnsweredText[entry.answer]), t(entry.in_sample ? 'in the current sample' : 'left the sample'), entry.differs && t('different from the runs')].filter(Boolean).join(' · ')}</p>
      </div></li>)}</ul>
    </details>}
    <div className="audit-group audit-abstract">
      <p className="audit-group-head">{t('Sample of works left out at the abstract stage (view and manual selection)')}</p>
      <p className="queue-muted">{t('To include or exclude one of these, find it in the source list and use its own controls. An inclusion there does not send it to full-text reading: it goes straight into the answer’s input. Sending it back to full-text reading is not built yet.')}</p>
      {(['A1', 'A2'] as const).map(stratum => <div key={stratum}>
        <p className="audit-subhead">{t(auditStratumLabels[stratum])} <small>{t('works in this group: {n}', { n: count(audit.abstract[stratum].size) })}</small></p>
        {audit.abstract[stratum].rows.length ? <ul className="audit-rows">{audit.abstract[stratum].rows.map(row => <AbstractRow key={row.work_id} row={row}
          onOpen={() => onOpenSource(row.source_version_id)} onShowInSources={() => onShowInSources(row.work_id)} />)}</ul>
          : <p className="empty-inline">{t('No work is in this group.')}</p>}
      </div>)}
    </div>
  </section>
}

function AuditRowItem({ researchId, row, busy, onOpen, onAnswer, onUndo }: {
  researchId: string; row: AuditRow; busy: boolean; onOpen: () => void; onAnswer: (answer: AuditAnswer) => void; onUndo: () => void
}) {
  const [detail, setDetail] = useState<AuditRowView | null>(null)
  const [open, setOpen] = useState(false)
  const show = () => {
    setOpen(value => !value)
    if (!detail) void api.auditRow(researchId, row.source_version_id).then(setDetail, () => setDetail({ row: null, detail: null }))
  }
  return <li className="audit-row">
    <div className="audit-row-main">
      <button type="button" className="queue-decided-title" onClick={onOpen}>{row.title}</button>
      <p className="queue-muted"><span className={`ref-pill is-${versionTones[row.version_label ?? ''] ?? 'unstated'}`}>{versionText(row.version_label)}</span> {t('The two runs decided: {decision}', { decision: t(auditStratumLabels[row.stratum]) })}</p>
      <p className="audit-question">{t('Does this work meet the criterion?')}</p>
      <button type="button" className="queue-link" aria-expanded={open} onClick={show}>{t(open ? 'Hide what the runs said' : 'Show what the runs said')}</button>
      {open && detail?.detail && <ul className="audit-runs">{detail.detail.runs.map(run => <li key={run.run_no}>
        <strong>{t('Run {n}', { n: run.run_no })}</strong>
        {run.parts.map(part => <p key={part.part}>{part.part}: {part.label}{part.quote ? <> — <q>{part.quote}</q>{part.page !== null ? ` (${pageLocator(part.page, part.rendition)})` : ''}{part.quote_verified ? '' : ` · ${t('quote not found in the text')}`}</> : ''}</p>)}
      </li>)}</ul>}
    </div>
    {row.answered
      ? <div className="audit-answered"><p className="queue-muted">{t('You answered: {answer}', { answer: t(queueAnswerLabels[row.answered.answer]) })}</p>
        <Button variant="ghost" size="sm" disabled={busy} onClick={onUndo} aria-label={t('Undo your audit answer on {title}', { title: row.title })}><RotateCcw size={14} aria-hidden />{t('Undo')}</Button></div>
      : <div className="queue-answers audit-answers" role="group" aria-label={t('Your answer on {title}', { title: row.title })}>
        {ANSWERS.map(choice => <Button key={choice} size="sm" variant="outline" disabled={busy} onClick={() => onAnswer(choice)}>{t(queueAnswerLabels[choice])}</Button>)}
      </div>}
  </li>
}

function AbstractRow({ row, onOpen, onShowInSources }: { row: AuditAbstractRow; onOpen: () => void; onShowInSources: () => void }) {
  return <li className="audit-row">
    <div className="audit-row-main">
      <button type="button" className="queue-decided-title" onClick={onOpen}>{row.title}</button>
      <p className="queue-muted">{t('Reason code: {code}', { code: row.reason_code })}</p>
      {row.quotes.filter(q => q.quote).map(q => <p key={`${q.run_no}-${q.quote}`} className="audit-quote">{t('Run {n}', { n: q.run_no })}: <q>{q.quote}</q></p>)}
    </div>
    <div className="audit-answered">
      {row.selection.state === 'included' && <p className="queue-muted">{t('Included')}</p>}
      <button type="button" className="queue-link" onClick={onShowInSources} aria-label={t('Find {title} in the source list', { title: row.title })}>{t('Find it in the source list')}</button>
    </div>
  </li>
}
