import { BookOpen, Copy, MessageSquare, Pause, PencilLine, Play, RotateCw, Search, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { type Claim, type FollowupTurn, type Source } from '../api'
import { locatorText, pauseReasonText, versionText } from '../labels'
import { MathText } from '../MathText'
import { useToast } from '../Toast'
import { t } from '../i18n'
import { writeClipboard } from '../clipboard'
import { followupClaim, splitQuotes } from './followupData'

// Follow-up questions in the thread (mockup `turnHtml()`, R31, UI parity S22b). Each turn is one stored `followup_answer`
// run (D11): the "Question" bubble, its two step lines, then the short answer with its citation chips. Everything shown is
// the stored turn: the step lines read the turn's stored step rows (`progress`) and, once published, the passages the call
// was given (`passages_given`, its allowlist); nothing is estimated. A follow-up starts no search; "Search for new works on
// this" saves a new question revision only when pressed. An unverified draft shows its issues and no claim; a turn the
// passages do not answer says so.

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const PUBLISHED = new Set(['answered', 'partly_answered', 'not_answered'])
type StepState = 'done' | 'running' | 'attention'
function StepLine({ state, icon: Icon, children }: { state: StepState; icon: typeof BookOpen; children: string }) {
  return <li className={`followup-step is-${state}`}>
    <span className="followup-step-line">
      <span className="followup-step-icon" role="img" aria-label={t(state === 'done' ? 'Done' : state === 'running' ? 'In progress' : 'Stopped here')}>
        {state === 'running' ? <span className="step-spin" /> : state === 'attention' ? <TriangleAlert size={16} aria-hidden /> : <Icon size={16} aria-hidden />}
      </span>
      <span className={state === 'running' ? 'shimmer-text' : undefined}>{children}</span>
    </span>
  </li>
}

// The two step lines of a turn (mockup: "Looked in the N passages from this research", "Wrote a short answer").
function steps(turn: FollowupTurn) {
  const live = turn.status === 'pending' && ACTIVE.has(turn.run.status)
  const given = PUBLISHED.has(turn.status) || turn.status === 'unverified_draft' ? turn.passages_given : turn.progress.passages_selected
  const lines: { state: StepState; icon: typeof BookOpen; text: string }[] = []
  if (turn.status === 'no_passages') return [{ state: 'attention' as const, icon: BookOpen, text: t('This research held no passage to give') }]
  if (given === null) {
    lines.push(live ? { state: 'running', icon: BookOpen, text: t('Looking in the passages from this research') }
      : { state: 'attention', icon: BookOpen, text: t('The passages were not chosen') })
    return lines
  }
  lines.push({ state: 'done', icon: BookOpen, text: t(given === 1 ? 'Looked in the {n} passage from this research' : 'Looked in the {n} passages from this research', { n: given }) })
  // The second round (D50): the model asked the library for more and these passages came in.
  const more = turn.progress.more_passages
  if (more) {
    // Read only once the second call came back; a selection alone is not a reading.
    lines.push(turn.progress.more_step === 'succeeded'
      ? { state: 'done', icon: Search, text: t(more === 1 ? 'Searched this research again and read {n} more passage' : 'Searched this research again and read {n} more passages', { n: more }) }
      : live ? { state: 'running', icon: Search, text: t('Searching this research again') }
        : turn.progress.more_error === 'invalid_model_output'
          ? { state: 'attention', icon: Search, text: t('Searched this research again; that answer failed validation') }
          : { state: 'attention', icon: Search, text: t('Searched this research again; the new passages were not read') })
  }
  if (PUBLISHED.has(turn.status)) lines.push({ state: 'done', icon: PencilLine, text: t('Wrote a short answer') })
  else if (turn.status === 'unverified_draft') lines.push({ state: 'attention', icon: PencilLine, text: t('The short answer failed validation') })
  else if (live) lines.push({ state: 'running', icon: PencilLine, text: t('Writing a short answer') })
  else lines.push({ state: 'attention', icon: PencilLine, text: t(turn.progress.answer_step === 'succeeded' ? 'Wrote a short answer; not published' : 'No short answer was written') })
  return lines
}

export type FollowupTurnActions = {
  busy: boolean
  // A run of this research is active: a new question, a resume or a new revision waits for it (one active run).
  locked: boolean
  canSearch: boolean
  citing: string | null
  onCite: (claim: Claim, opener: HTMLElement) => void
  onControl: (runId: string, action: 'resume' | 'cancel') => void
  onAskAgain: (question: string) => void
  onSearchNew: (turn: FollowupTurn) => void
}

export function FollowupTurnView({ turn, sources, actions }: { turn: FollowupTurn; sources: Source[]; actions: FollowupTurnActions }) {
  const toast = useToast()
  const live = turn.status === 'pending' && ACTIVE.has(turn.run.status)
  const answer = turn.answer
  const claims = answer ? answer.claims.map(c => followupClaim(turn, c, sources)) : []
  // The chip names its first source by its key, else the numbers of the turn's cited passages in order.
  const numbers = new Map<string, number>()
  claims.forEach(c => c.evidence.forEach(e => { if (!numbers.has(e.passage_id)) numbers.set(e.passage_id, numbers.size + 1) }))
  const chip = (claim: Claim) => {
    if (!claim.evidence.length) return null
    const first = claim.evidence[0]
    const others = new Set(claim.evidence.map(e => e.source_version_id)).size - 1
    const label = first.source_key ? `${first.source_key}${others > 0 ? ` +${others}` : ''}` : `[${[...new Set(claim.evidence.map(e => numbers.get(e.passage_id)))].join(', ')}]`
    const title = claim.evidence.map(e => [e.title, versionText(e.version_label), locatorText(e), e.removed_from_research && t('Removed from this research')].filter(Boolean).join(' · ')).join('\n')
    return <button type="button" className={`cite-chip thread-cite${actions.citing === claim.id ? ' is-on' : ''}`} title={title} aria-expanded={actions.citing === claim.id}
      onClick={e => actions.onCite(claim, e.currentTarget)}>{label}</button>
  }
  const copy = async () => {
    const text = [`${t('Question')}: ${turn.question}`, '',
      ...claims.map(c => `${c.text}${c.evidence.length ? ` (${c.evidence.map(e => `${e.title}, ${locatorText(e)}`).join('; ')})` : ''}`),
      ...(answer?.unanswered_aspects.length ? ['', `${t('Not answered by these passages')}:`, ...answer.unanswered_aspects.map(a => `- ${a}`)] : [])].join('\n')
    try { await writeClipboard(text); toast('success', t('Follow-up answer copied to clipboard.')) }
    catch { toast('error', t('Could not copy to the clipboard.')) }
  }
  const userPaused = turn.run.status === 'paused' && turn.run.pause_reason === 'user_requested'
  const searchable = actions.canSearch && !turn.stale_scope && ['not_answered', 'partly_answered', 'no_passages'].includes(turn.status)
  const asked = splitQuotes(turn.question)
  return <section className="followup-turn">
    <div className="followup-q">{asked.quotes.map((quote, i) => <blockquote className="followup-quote" key={i}><MathText text={quote} /></blockquote>)}
      <b><MessageSquare size={16} aria-hidden />{t('Question')}</b> <span>{asked.text}</span></div>
    <ol className="followup-steps">{steps(turn).map(line => <StepLine key={line.text} state={line.state} icon={line.icon}>{line.text}</StepLine>)}</ol>
    {turn.stale_scope && <p className="followup-note">{t('Asked under revision {n} of the question.', { n: turn.scope_revision })}</p>}
    {turn.status === 'pending' && !live && <div className={`chat-note notice followup-notice ${turn.run.status === 'paused' ? (userPaused ? 'is-warning' : 'is-error') : turn.run.status === 'failed' ? 'is-error' : 'is-neutral'}`}>
      {turn.run.status === 'paused' && userPaused ? <Pause size={16} aria-hidden /> : <TriangleAlert size={16} aria-hidden />}
      <div className="notice-body">
        {turn.run.status === 'paused'
          ? <p>{userPaused ? <><b>{t('Paused after the current call.')}</b> {t('Nothing was lost: the finished steps are kept and will not run again.')}</> : <b>{pauseReasonText(turn.run.pause_reason, turn.run.error)}</b>}</p>
          : turn.run.status === 'cancelled' ? <p>{t('Cancelled. No answer was published.')}</p>
          : turn.run.status === 'failed' ? <p><b>{pauseReasonText(turn.run.pause_reason, turn.run.error) || t('This follow-up stopped before its answer was published.')}</b></p>
          : <p>{t('This follow-up stopped before its answer was published.')}</p>}
        <div className="notice-actions">
          {turn.run.status === 'paused'
            ? <>
              <Button size="sm" disabled={actions.busy || actions.locked} onClick={() => actions.onControl(turn.run.id, 'resume')}><Play size={14} aria-hidden />{t('Resume run')}</Button>
              <Button variant="outline" size="sm" className="notice-ghost" disabled={actions.busy} onClick={() => actions.onControl(turn.run.id, 'cancel')}>{t('Cancel run')}</Button>
            </>
            : <Button variant="outline" size="sm" className="notice-ghost" disabled={actions.busy || actions.locked} onClick={() => actions.onAskAgain(turn.question)}><RotateCw size={14} aria-hidden />{t('Ask again')}</Button>}
        </div>
      </div>
    </div>}
    {turn.status === 'no_passages' && <div className="chat-note notice followup-notice is-warning"><TriangleAlert size={16} aria-hidden />
      <div className="notice-body"><p>{t('This research held no passage to give, so no model was asked and no search was run.')}</p></div>
    </div>}
    {turn.status === 'unverified_draft' && <div className="chat-note notice followup-notice is-error"><TriangleAlert size={16} aria-hidden />
      <div className="notice-body">
        <p>{t('The model output did not pass validation, so it is not shown as a cited answer.')}</p>
        {turn.issues.length > 0 && <ul className="answer-notice-issues">{turn.issues.map(i => <li key={`${i.code}${i.path}`}>{t('{code} at {path}', { code: i.code, path: i.path })}</li>)}</ul>}
      </div>
    </div>}
    {answer && <>
      {answer.outcome !== 'answered' && <p className="followup-outcome">{t(answer.outcome === 'not_answered' ? 'The passages in this research do not answer this.' : 'The passages in this research answer part of this.')}</p>}
      {turn.stale_selection && <p className="followup-note">{t('Your source selection changed after this answer was written; it reflects the earlier selection.')}</p>}
      {claims.length > 0 && <div className="prose followup-prose"><p>{claims.map(claim => <span className="claim" key={claim.id}><MathText text={claim.text} />
        {claim.support_type === 'analyst_inference' && <span className="support-badge">{t('interpretation')}</span>}
        {chip(claim)}</span>)}</p></div>}
      {answer.unanswered_aspects.length > 0 && <div className="followup-gaps"><p>{t('Not answered by these passages')}</p>
        <ul>{answer.unanswered_aspects.map(a => <li key={a}><MathText text={a} /></li>)}</ul></div>}
      {turn.report_change && <p className="followup-note">{turn.report_change.run_id
        ? turn.report_change.answer_status === 'structurally_valid'
          ? t('This asked for a change to the report; report V{n} was written for it.', { n: turn.report_change.report_version ?? '' })
          : turn.report_change.run_status && ['queued', 'running', 'pause_requested', 'paused'].includes(turn.report_change.run_status)
            ? t('This asked for a change to the report; a new report version is being written for it.')
            : t('This asked for a change to the report, but no new report version could be written; the report was not changed.')
        : t(turn.report_change.not_started === 'scope_revised' ? 'This asked for a change to the report, but the question was revised since; the report was not changed.'
          : turn.report_change.not_started === 'nothing_included' ? 'This asked for a change to the report, but no source is included; the report was not changed.'
          : 'This asked for a change to the report, but another run was active; the report was not changed. Ask again when it ends.')}</p>}
    </>}
    {!live && turn.status !== 'pending' && (searchable || claims.length > 0) && <div className="followup-acts">
      {searchable && <Button variant="outline" size="sm" className="answer-pill" disabled={actions.busy || actions.locked} onClick={() => actions.onSearchNew(turn)}><Search size={16} className="size-4" aria-hidden />{t('Search for new works on this')}</Button>}
      {claims.length > 0 && <Button variant="ghost" size="icon-sm" className="answer-ib" aria-label={t('Copy follow-up answer')} title={t('Copy follow-up answer')} onClick={() => { void copy() }}><Copy size={16} aria-hidden /></Button>}
    </div>}
  </section>
}
