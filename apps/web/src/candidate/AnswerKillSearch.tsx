import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CircleX, SearchCheck } from 'lucide-react'
import { Dialog, DialogBody, DialogContent, DialogFooter } from '@/components/ui/dialog'
import { api, type AnswerCandidate, type AnswerCandidates, type AnswerCandidateSearch, type CandidateCard } from '../api'
import { ModelName } from '../ModelName'
import { useModelText } from '../modelText'
import { pauseReasonText } from '../labels'
import { t, uiLocale } from '../i18n'
import { useToast } from '../Toast'
import type { CandidateSelection } from './CandidatesView'
import { errorText, label, reasonText, relationLabels, relationTones, runReasonLabels, statusLabels } from './labels'
import '../research/kit.css'
import './candidate.css'

// Kill search from the answer's Next steps (D98). The answer thread only writes the person's sentence and shows a
// summary of what the Candidates panel stored; the card, the plan, the search and the matrix stay in that panel.
// Every number here is a stored count from the API, never a constant of the plan.

const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
const shortDate = (date: string) => new Date(date).toLocaleString(uiLocale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])

export type ClaimTarget = { aspectIndex: number | null; aspectText: string | null }

// "Search earlier work for a claim": the topic the answer did not answer stays above the box as read-only context and
// the box starts empty, so the claim is the person's sentence. Saving makes a candidate and opens the Candidates panel
// at it; the first button also starts the breakdown (a model step, no search). The search starts only in the panel.
export function ClaimDialog({ researchId, answerId, answerVersion, target, decompose, dark, onClose, onSaved }: {
  researchId: string; answerId: string; answerVersion: number; target: ClaimTarget; decompose: AnswerCandidates['decompose'] | null; dark: boolean
  onClose: () => void; onSaved: (selection: CandidateSelection) => void
}) {
  const modelText = useModelText()
  const toast = useToast()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const [opener] = useState(() => document.activeElement as HTMLElement | null)
  const noModel = !decompose?.model
  // One request key per pending submission: a retry of the same sentence reuses it, a changed sentence gets a new one.
  const submission = useRef<{ text: string; key: string } | null>(null)
  // A dialog that unmounted while its save was in flight (a new answer took its place) does nothing after the save:
  // no toast, no breakdown, and no callback that could close a dialog opened since or open this answer's candidate.
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const empty = !text.trim()
  async function save(mode: 'decompose' | 'edit') {
    if (busy || empty || (mode === 'decompose' && noModel)) return
    setBusy(true); setProblem('')
    let card: CandidateCard
    try {
      if (submission.current?.text !== text.trim()) submission.current = { text: text.trim(), key: crypto.randomUUID() }
      const created = await api.openAnswerCandidate(researchId, answerId, { aspect_index: target.aspectIndex, text }, submission.current.key)
      card = created.card
      if (!mounted.current) return
      if (created.reused) { toast('success', t('A claim was already written from this topic; it is opened instead.')); onSaved({ id: card.id, card }); return }
    } catch (e) { if (mounted.current) { setProblem(errorText(e)); setBusy(false) } return }
    if (mode === 'decompose') {
      try { await api.decomposeCandidate(researchId, card.id); if (mounted.current) toast('success', t('Claim saved. Breaking it into parts has started; nothing is searched yet.')) }
      catch (e) { if (mounted.current) toast('error', t('Claim saved, but breaking it into parts did not start: {error}', { error: errorText(e) })) }
      if (mounted.current) onSaved({ id: card.id, card })
    } else {
      toast('success', t('Claim saved. Write its card in the Candidates panel.'))
      onSaved({ id: card.id, card, focus: 'edit' })
    }
  }
  const reasonId = 'claim-dialog-reason'
  const reason = busy ? t('Saving…') : empty ? t('Enter a sentence to save.') : ''
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose() }}>
    <DialogContent className={`claim-dialog mk${dark ? ' dark' : ''}`} icon={<SearchCheck size={16} aria-hidden />} title={t('Search earlier work for a claim')}
      finalFocus={() => opener?.isConnected ? opener : true}>
      <DialogBody>
        {target.aspectText && <div className="claim-dialog-context"><span>{target.aspectIndex !== null ? t('A topic the answer did not answer (V{v}, topic {n})', { v: answerVersion, n: target.aspectIndex + 1 }) : t('A topic the answer did not answer')}</span>
          <p data-stored-text>{target.aspectText}</p></div>}
        <label className="lbl claim-dialog-label">{t('Claim')}
          <textarea className="field" autoFocus rows={4} maxLength={2000} value={text} placeholder={t('What, under which condition, with what result. Example shape: “X changes Z under condition Y.”')}
            aria-describedby="claim-dialog-help" onChange={e => setText(e.target.value)} />
        </label>
        <p id="claim-dialog-help" className="foot-note">{t('Write one testable sentence. The model does not change it: it breaks it into parts and you approve them.')} {t('{n}/{max} characters', { n: text.length, max: 2000 })}</p>
        {problem && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{problem}</span></div>}
      </DialogBody>
      <DialogFooter className="claim-dialog-foot">
        <div className="acts">
          <button type="button" className="btn-pri" disabled={busy || empty || noModel} aria-describedby={busy || empty || noModel ? `${reasonId} claim-dialog-ceiling` : 'claim-dialog-ceiling'} onClick={() => void save('decompose')}>{t('Save and break into parts')}</button>
          <button type="button" className="ghost" disabled={busy || empty} aria-describedby={busy || empty ? reasonId : undefined} onClick={() => void save('edit')}>{t('I will write the card myself')}</button>
        </div>
        {reason && <p id={reasonId} className="foot-note">{reason}</p>}
        <p id="claim-dialog-ceiling" className="foot-note claim-dialog-ceiling">{!decompose ? t('Loading the model…')
          : noModel ? t('No model is chosen for this research, so the claim cannot be broken into parts here. You can save it and write the card yourself.')
          : <>{t('Breaking into parts:')} <ModelName connection={decompose.connection} text={modelText(decompose.model, decompose.reasoning_effort)} /> · {t(decompose.max_model_calls === 1 ? 'at most {n} model call (retries included)' : 'at most {n} model calls (retries included)', { n: count(decompose.max_model_calls) })} · {t('no search')}</>}</p>
        <p className="foot-note">{t('Nothing is searched here. The search starts only in the Candidates panel, after you see its plan.')}</p>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}

// The computed status as a sentence attributed to the model or to the stored counts; never a verdict of DEIXIS and
// never a word for absence in the literature.
function verdict(search: AnswerCandidateSearch) {
  const e = search.execution, status = search.status
  if (search.outcome === 'running') return t('Searching · {done}/{planned} queries done · {assessed}/{kept} works assessed', { done: count(e.queries_recorded), planned: count(e.queries_planned), assessed: count(e.assessed), kept: e.kept === null ? '–' : count(e.kept) })
  if (search.outcome === 'paused') return t('Paused · {done}/{planned} queries done · {assessed}/{kept} works assessed', { done: count(e.queries_recorded), planned: count(e.queries_planned), assessed: count(e.assessed), kept: e.kept === null ? '–' : count(e.kept) })
  if (search.outcome === 'failed' || search.outcome === 'stopped') return `${t(search.outcome === 'failed' ? 'The search did not complete.' : 'The search was stopped.')} ${reasonText(status)}`
  if (status.status === 'closed') return t(e.works_stating_whole_claim === 1 ? 'The model marked quotes for every part of the claim under the same conditions in {k} work.' : 'The model marked quotes for every part of the claim under the same conditions in {k} works.', { k: count(e.works_stating_whole_claim) })
  if (status.status === 'narrowed') return t(e.assessed === 1 ? 'The model found partial overlap or inference-based support in {k} of the {n} work assessed.' : 'The model found partial overlap or inference-based support in {k} of the {n} works assessed.', { k: count(e.works_with_support), n: count(e.assessed) })
  if (status.status === 'open') return e.records_returned === 0 ? t('The search returned no works.')
    : t(e.assessed === 1 ? 'No match was found in the abstract and passages given to the model for the {n} work assessed.' : 'No match was found in the abstracts and passages given to the model for the {n} works assessed.', { n: count(e.assessed) })
  return `${t('The search did not settle the claim.')} ${reasonText(status)}`
}
const tone = (search: AnswerCandidateSearch) => search.outcome === 'running' ? 'run' : search.outcome === 'paused' ? 'pause' : search.outcome !== 'completed' ? 'bad' : search.status.status

function executionLine(search: AnswerCandidateSearch) {
  const e = search.execution
  const queries = [t('{ok} of {planned} queries completed', { ok: count(e.queries_succeeded), planned: count(e.queries_planned) })]
  if (e.queries_failed) queries.push(t('{n} failed', { n: count(e.queries_failed) }))
  if (e.queries_outcome_unknown) queries.push(t('{n} with unknown outcome', { n: count(e.queries_outcome_unknown) }))
  if (search.outcome === 'running' || search.outcome === 'paused') {
    const pending = e.queries_planned - e.queries_recorded
    if (pending > 0) queries.push(t('{n} not run yet', { n: count(pending) }))
  }
  const parts = [queries.join(', ')]
  if (e.hits_recorded && e.found !== null && e.unique !== null) parts.push(t('{found} records, {unique} distinct works', { found: count(e.found), unique: count(e.unique) }))
  else if (e.records_returned) parts.push(t('{n} records so far', { n: count(e.records_returned) }))
  if (e.kept !== null) {
    const works = [t('{assessed} of {kept} kept works assessed', { assessed: count(e.assessed), kept: count(e.kept) })]
    if (e.insufficient_access) works.push(t('{n} without usable text', { n: count(e.insufficient_access) }))
    if (e.not_assessed_budget) works.push(t('{n} outside the budget', { n: count(e.not_assessed_budget) }))
    if (e.pending && search.outcome !== 'running' && search.outcome !== 'paused') works.push(t('{n} not assessed', { n: count(e.pending) }))
    parts.push(works.join(', '))
  }
  return `${t('Execution:')} ${parts.join(' · ')}`
}

function readingLine(search: AnswerCandidateSearch) {
  const r = search.reading
  if (!r.assessed_works) return null
  const parts = [t(r.abstracts === 1 ? '{n} abstract' : '{n} abstracts', { n: count(r.abstracts) }), t(r.stored_passages === 1 ? '{n} stored passage' : '{n} stored passages', { n: count(r.stored_passages) })]
  if (r.depths.metadata_only) parts.push(t('{n} metadata only', { n: count(r.depths.metadata_only) }))
  parts.push(r.full_text ? t('{n} full texts', { n: count(r.full_text) }) : t('no full text'))
  return `${t('Given to the model:')} ${parts.join(' · ')}`
}

// One line per candidate written from this answer (mockup `.ksum`): where it came from, the claim, the stored
// result and how far the search got, then the ways into the Candidates panel.
export function AnswerKillSummary({ row, onOpen, onOpenWork, onResume, busy }: {
  row: AnswerCandidate; onOpen: (selection: CandidateSelection) => void; onOpenWork: (row: AnswerCandidate, sourceVersionId: string, killSearchId: string) => void
  onResume: (runId: string) => void; busy: boolean
}) {
  const search = row.search, run = row.run
  const paused = run?.status === 'paused'
  const searching = run?.kind === 'kill_search' && ACTIVE.has(run.status)
  const breaking = run?.kind === 'claim_decomposition' && ACTIVE.has(run.status)
  const changed = search && !row.current_version_searched && row.current_version > 0
  const shown = search && (!changed || ['completed', 'failed', 'stopped'].includes(search.outcome)) ? search : null
  // Links name the search this summary describes, so the panel opens that search, not the current version's latest.
  const open = (focus?: CandidateSelection['focus']) => onOpen({ id: row.candidate_id, focus, search: search?.kill_search_id })
  let line: ReactNode, lineTone = 'idle'
  if (paused && run) { line = <>{t('Paused: {reason}', { reason: run.pause_reason ? (runReasonLabels[run.pause_reason] ? label(runReasonLabels, run.pause_reason) : pauseReasonText(run.pause_reason)) : t('no reason was stored.') })} {t('It can resume where it stopped.')}</>; lineTone = 'pause' }
  else if (breaking) { line = t('Breaking the claim into testable parts…'); lineTone = 'run' }
  else if (searching && (!search || search.version !== row.current_version || !row.current_version_searched)) { line = t('Preparing the search terms…'); lineTone = 'run' }
  else if (!row.current_version) {
    const failed = row.latest_run?.kind === 'claim_decomposition' && row.latest_run.status === 'failed'
    line = failed ? t('Breaking into parts did not complete: {reason}', { reason: label(runReasonLabels, row.latest_run!.pause_reason ?? 'model_call_failed') })
      : t('No card yet. Break the claim into parts or write the card in the Candidates panel.')
    lineTone = failed ? 'bad' : 'idle'
  } else if (!search) line = t('Card V{n} is ready; nothing has been searched. The search starts in the Candidates panel.', { n: row.current_version })
  else if (changed) { line = <>{t('Card V{n} has no search yet', { n: row.current_version })} · {t('V{m} result:', { m: search.version })} {verdict(search)}</>; lineTone = 'idle' }
  else { line = verdict(search); lineTone = tone(search) }
  const sourceLabel = row.aspect_index !== null ? t('From topic {n} of this answer', { n: row.aspect_index + 1 }) : t('From this answer')
  const decision = row.owner ? t('Your decision (V{n}): {status}', { n: row.owner.version, status: label(statusLabels, row.owner.status) }) : t('Your decision: none yet')
  const reading = shown && readingLine(shown)
  return <article className="ksum" aria-label={t('Earlier-work search')}>
    <div className="ksum-h"><strong>{t('Earlier-work search')}</strong><span aria-hidden>·</span><span>{row.current_version ? t('Card V{n}', { n: row.current_version }) : t('No card yet')}</span>
      <span aria-hidden>·</span><span>{shortDate(search?.created_at ?? row.created_at)}</span><span aria-hidden>·</span><span>{sourceLabel}</span></div>
    <div className="ksum-b">
      <p className="ksum-claim" data-stored-text title={row.claim_statement ?? row.origin_text}>{row.claim_statement ?? row.origin_text}</p>
      <p className={`ksum-verdict is-${lineTone}`} role={lineTone === 'run' ? 'status' : undefined}>{lineTone === 'run' ? <span className="spin" aria-hidden /> : <span className="ksum-dot" aria-hidden />}<span>{line}</span></p>
      {search && <p className="foot-note ksum-fact">{changed && <>{t('V{m} search:', { m: search.version })} </>}{executionLine(search)}</p>}
      {reading && <p className="foot-note ksum-fact">{reading}</p>}
      {shown && shown.top_works.length > 0 && <ul className="ksum-works" aria-label={t('Works with a recorded relation')}>{shown.top_works.map(work => <li key={work.source_version_id}>
        <button type="button" className="link ksum-title" data-stored-text onClick={() => onOpenWork(row, work.source_version_id, shown.kill_search_id)}>{work.title}</button>{work.year && <span className="foot-note"> · {work.year}</span>}
        {work.states_whole_claim && <span className="foot-note"> · {t('the model marked the whole claim in this work')}</span>}
        <span className="ksum-els">{work.elements.map(el => <span key={el.element_id} className={`rel ${relationTones[el.relation] ?? 'none'}`} title={el.text}>
          <span className="sr-only">{t('Part {n}:', { n: el.position })} {el.text} · </span><span aria-hidden>{t('P{n}', { n: el.position })}</span> {label(relationLabels, el.relation)}</span>)}</span>
      </li>)}</ul>}
      {search && <p className="foot-note ksum-caveat">{t('This search can miss related works; finding no match is not evidence of originality.')} {t('Semantic support not checked.')}</p>}
    </div>
    <div className="ksum-f acts">
      {paused && run && <button type="button" className="ghost" disabled={busy} onClick={() => onResume(run.id)}>{t('Resume')}</button>}
      <button type="button" className="link" onClick={() => open(search ? 'matrix' : undefined)}>{t(search ? 'Open the claim matrix' : 'Open in the Candidates panel')}</button>
      {shown && shown.is_current_version && shown.outcome !== 'running' && shown.outcome !== 'paused' && <button type="button" className="link" onClick={() => open('review')}>{t('Review with another model')}</button>}
      {search && row.current_version_searched && <button type="button" className="link" onClick={() => open('decision')}>{t('Record my decision')}</button>}
      <span className="cst yours">{decision}</span>
    </div>
  </article>
}
