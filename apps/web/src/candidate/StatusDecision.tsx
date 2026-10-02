import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { CandidateCard, CandidateComputed, CandidateStatus } from '../api'
import { api } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { dateText, errorText, label, reasonText, statusLabels, warningLabels } from './labels'
import { useReturnFocus } from './focus'

export function StatusDecision({ card, computed, computedVersion, previous, beginMutation, onChanged }: {
  card: CandidateCard; computed: CandidateComputed; computedVersion: number; previous: CandidateComputed | null; beginMutation: () => number; onChanged: (card: CandidateCard, request: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<CandidateStatus>('undecided')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const control = useRef<HTMLButtonElement>(null)
  const { rememberFocus, restoreFocus } = useReturnFocus()
  const close = () => { setOpen(false); restoreFocus() }
  const facts = computed.facts, owner = card.status?.owner
  async function save() {
    if (!card.current_version_id || busy) return
    if (!reason.trim()) { setProblem(t('Enter a non-blank reason.')); return }
    const request = beginMutation()
    setBusy(true); setProblem('')
    try { onChanged(await api.candidateOwnerDecision(card.research_id, card.id, card.current_version_id, { status, reason }), request); close(); setReason('') }
    catch (e) { setProblem(errorText(e)) }
    finally { setBusy(false) }
  }
  return <section className="candidate-section candidate-status" aria-label={t('Status and your decision')}>
    <h3>{t('Status and your decision')}</h3><p>{t('Computed: {status}', { status: label(statusLabels, computed.status) })} · {t('Yours: {status}', { status: owner ? label(statusLabels, owner.status).toLocaleLowerCase() : t('not recorded') })}</p>
    {computedVersion !== card.current_version && <p>{t('Computed status is for version {searched}; your decisions are for the current version {current}.', { searched: computedVersion, current: card.current_version })}</p>}
    <div className="candidate-status-columns"><section aria-label={t('Computed status')}><h4>{t('Computed status')} · {label(statusLabels, computed.status)}</h4>
      <p>{reasonText(computed)}</p><h4>{t('All status reasons')} · {computed.reasons.length}</h4>{computed.reasons.length ? <ul>{computed.reasons.map((code, i) => <li key={i}>{reasonText(computed, code)}</li>)}</ul> : <p>{t('None.')}</p>}
      <p>{t('Found {found}; kept for assessment {kept}; assessed {assessed}; not read {unread} ({cut} ranked lower and {incomplete} kept assessments incomplete); duplicates merged {duplicates}; queries {total}, succeeded {succeeded}, failed {failed}, unknown outcome {unknown}.', { found: facts.found, kept: facts.kept, assessed: facts.assessed, unread: facts.unread, cut: facts.rank_cut, incomplete: facts.kept - facts.assessed, duplicates: facts.duplicates, total: facts.queries_total, succeeded: facts.queries_succeeded, failed: facts.queries_failed, unknown: facts.queries_unknown })}</p>
      <p>{t('Reading depths of kept works: abstract {abstract}, stored passages {stored}, metadata only {metadata}.', { abstract: facts.reading_depths.abstract, stored: facts.reading_depths.stored_passages, metadata: facts.reading_depths.metadata_only })}</p>
      <h4>{t('Warnings')} · {computed.warnings.length}</h4>{computed.warnings.length ? <ul>{computed.warnings.map((warning, i) => <li key={i}>{label(warningLabels, warning)}</li>)}</ul> : <p>{t('None.')}</p>}
      <p className="candidate-fine">{t('Code derived this status from the matrix below. It is not a model verdict, and it says nothing about works that were not read.')}</p>
      {previous && <p>{t('Earlier search: {status}', { status: label(statusLabels, previous.status) })}</p>}
    </section><section aria-label={t('Your decision')}><h4>{t('Your decision')}</h4>{owner ? <><p>{label(statusLabels, owner.status)} · {dateText(owner.created_at)}</p><p data-stored-text>{owner.reason}</p></> : <p>{t('not recorded')}</p>}
      <p>{t('Your decision is a note of your own. It is not independent evidence and does not change the computed status.')}</p>
      <h4>{t('Decision history for the current version')} · {card.owner_decisions.length}</h4>{card.owner_decisions.length ? <ol>{[...card.owner_decisions].sort((a, b) => b.created_at.localeCompare(a.created_at)).map(item => <li key={item.id}>{label(statusLabels, item.status)} · {dateText(item.created_at)}<p data-stored-text>{item.reason}</p></li>)}</ol> : <p>{t('None.')}</p>}
      <Button ref={control} variant="outline" aria-expanded={open} onClick={e => { if (open) close(); else { rememberFocus(e.currentTarget, () => control.current); setOpen(true) } }}>{t('Record my decision')}</Button>
      {open && <form className="candidate-form" onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); close() } }} onSubmit={e => { e.preventDefault(); void save() }}><label className="evidence-field"><span>{t('Decision status')}</span><select autoFocus value={status} onChange={e => setStatus(e.target.value as CandidateStatus)}>{Object.entries(statusLabels).map(([code, name]) => <option key={code} value={code}>{t(name)}</option>)}</select></label>
        <label className="evidence-field"><span>{t('Reason')}</span><small>{t('{n}/{max} characters', { n: reason.length, max: 2000 })}</small><textarea aria-label={t('Reason')} required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label>
        {problem && <Notice tone="error">{problem}</Notice>}<Button type="submit" disabled={busy} aria-describedby={busy ? 'candidate-decision-saving' : undefined}>{t('Save')}</Button>{busy && <p id="candidate-decision-saving" role="status">{t('Saving…')}</p>}
      </form>}
    </section></div>
  </section>
}
