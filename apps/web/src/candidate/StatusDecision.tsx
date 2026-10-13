import { useRef, useState, type ReactNode } from 'react'
import { ChevronRight, CircleX } from 'lucide-react'
import type { CandidateCard, CandidateComputed, CandidateStatus } from '../api'
import { api } from '../api'
import { t } from '../i18n'
import { dateText, errorText, label, reasonText, statusLabels, warningLabels } from './labels'
import { useReturnFocus } from './focus'

// "Status and your decision" (mockup `candDetail`): the status code computed from the matrix, the person's own decision
// beside it (never mixed in), why code reached that status, and Record my decision. The facts behind the status, its
// warnings and the decision history stay one disclosure away.
export function StatusDecision({ card, computed, computedVersion, previous, beginMutation, onChanged, actions }: {
  card: CandidateCard; computed: CandidateComputed; computedVersion: number; previous: CandidateComputed | null; beginMutation: () => number; onChanged: (card: CandidateCard, request: number) => void
  actions?: ReactNode
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
  return <section className="candidate-status" aria-labelledby={`candidate-status-${card.id}`}>
    <h4 className="sub" id={`candidate-status-${card.id}`}>{t('Status and your decision')}</h4>
    <p className="candidate-status-line"><span>{t('Computed:')}</span> <span className={`cst ${computed.status}`}>{label(statusLabels, computed.status)}</span>{owner && <> <span className={`cst yours ${owner.status}`}>{t('Yours: {status}', { status: label(statusLabels, owner.status) })}</span></>}</p>
    {computedVersion !== card.current_version && <p className="foot-note">{t('Computed status is for version {searched}; your decisions are for the current version {current}.', { searched: computedVersion, current: card.current_version })}</p>}
    <p className="foot-note candidate-reason">{reasonText(computed)}</p>
    <p className="foot-note">{t('Code derived this status from the matrix below. It is not a model verdict, and it says nothing about works that were not read.')}</p>
    {open ? <form className="ceditor candidate-form" onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); close() } }} onSubmit={e => { e.preventDefault(); void save() }}>
      <label className="lbl">{t('Your decision')}<select className="select" autoFocus value={status} onChange={e => setStatus(e.target.value as CandidateStatus)}>{Object.entries(statusLabels).map(([code, name]) => <option key={code} value={code}>{t(name)}</option>)}</select></label>
      <label className="lbl">{t('Reason')}<input className="field" aria-label={t('Reason')} required maxLength={2000} placeholder={t('Required')} value={reason} onChange={e => setReason(e.target.value)} /><small>{t('{n}/{max} characters', { n: reason.length, max: 2000 })}</small></label>
      <p className="foot-note">{t('Your decision is a note of your own. It is not independent evidence and does not change the computed status.')}</p>
      {problem && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{problem}</span></div>}
      <div className="acts"><button type="submit" className="btn-pri" disabled={busy} aria-describedby={busy ? 'candidate-decision-saving' : undefined}>{t('Record my decision')}</button><button type="button" className="ghost" disabled={busy} onClick={close}>{t('Cancel')}</button>{busy && <span id="candidate-decision-saving" role="status" className="foot-note">{t('Saving…')}</span>}</div>
    </form> : <div className="acts">
      <button ref={control} type="button" className="ghost" aria-expanded={open} onClick={e => { rememberFocus(e.currentTarget, () => control.current); setOpen(true) }}>{t('Record my decision')}</button>
      {actions}
    </div>}
    <details className="mk-more"><summary><ChevronRight size={14} aria-hidden />{t('Status details and your decisions')}</summary>
      <section aria-label={t('Computed status')}><h5>{t('All status reasons')} · {computed.reasons.length}</h5>{computed.reasons.length ? <ul>{computed.reasons.map((code, i) => <li key={i}>{reasonText(computed, code)}</li>)}</ul> : <p>{t('None.')}</p>}
        <p>{t('Found {found}; kept for assessment {kept}; assessed {assessed}; not read {unread} ({cut} ranked lower and {incomplete} kept assessments incomplete); duplicates merged {duplicates}; queries {total}, succeeded {succeeded}, failed {failed}, unknown outcome {unknown}.', { found: facts.found, kept: facts.kept, assessed: facts.assessed, unread: facts.unread, cut: facts.rank_cut, incomplete: facts.kept - facts.assessed, duplicates: facts.duplicates, total: facts.queries_total, succeeded: facts.queries_succeeded, failed: facts.queries_failed, unknown: facts.queries_unknown })}</p>
        <p>{t('Reading depths of kept works: abstract {abstract}, stored passages {stored}, metadata only {metadata}.', { abstract: facts.reading_depths.abstract, stored: facts.reading_depths.stored_passages, metadata: facts.reading_depths.metadata_only })}</p>
        <h5>{t('Warnings')} · {computed.warnings.length}</h5>{computed.warnings.length ? <ul>{computed.warnings.map((warning, i) => <li key={i}>{label(warningLabels, warning)}</li>)}</ul> : <p>{t('None.')}</p>}
        {previous && <p>{t('Earlier search: {status}', { status: label(statusLabels, previous.status) })}</p>}
      </section>
      <section aria-label={t('Your decision')}><h5>{t('Your decision')}</h5>{owner ? <><p>{label(statusLabels, owner.status)} · {dateText(owner.created_at)}</p><p data-stored-text>{owner.reason}</p></> : <p>{t('not recorded')}</p>}
        <h5>{t('Decision history for the current version')} · {card.owner_decisions.length}</h5>{card.owner_decisions.length ? <ol>{[...card.owner_decisions].sort((a, b) => b.created_at.localeCompare(a.created_at)).map(item => <li key={item.id}>{label(statusLabels, item.status)} · {dateText(item.created_at)}<p data-stored-text>{item.reason}</p></li>)}</ol> : <p>{t('None.')}</p>}
      </section>
    </details>
  </section>
}
