import { BookOpen, Copy, MessageSquare, Pause, PencilLine, Play, RotateCw, Search, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { type Claim, type FollowupSearchRequest, type FollowupSearchRun, type FollowupTurn, type FollowupWorkGroups, type Source } from '../api'
import { locatorText, pauseReasonText, providerName, serviceErrorSentence, serviceKind, versionText } from '../labels'
import { MathText } from '../MathText'
import { useToast } from '../Toast'
import { t } from '../i18n'
import { writeClipboard } from '../clipboard'
import { followupClaim, followupGroupClaims, splitQuotes, workTitle } from './followupData'

// Follow-up questions in the thread (mockup `turnHtml()`, R31, UI parity S22b). Each turn is one stored `followup_answer`
// run (D11): the "Question" bubble, its two step lines, then the short answer with its citation chips. Everything shown is
// the stored turn: the step lines read the turn's stored step rows (`progress`) and, once published, the passages the call
// was given (`passages_given`, its allowlist); nothing is estimated. A follow-up starts no search and opens no question
// revision (D67: the turn's "Search for new works on this" was removed). An unverified draft shows its issues and no claim; a turn the
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
  citing: string | null
  onCite: (claim: Claim, opener: HTMLElement) => void
  onControl: (runId: string, action: 'resume' | 'cancel') => void
  onAskAgain: (question: string) => void
  onSearch: (turnId: string) => void
  onShowCandidates: (opener: HTMLElement) => void
}

// The turn's search for works outside the research (D92): its step lines read the run's stored steps and summary.
function searchSteps(run: FollowupSearchRun) {
  const live = ACTIVE.has(run.status)
  const p = run.progress, c = run.summary.counts
  const lines: { state: StepState; icon: typeof BookOpen; text: string }[] = []
  if (p.query !== 'succeeded') {
    lines.push(live ? { state: 'running', icon: PencilLine, text: t('Writing search terms') } : { state: 'attention', icon: PencilLine, text: t('No search terms were written') })
    return lines
  }
  lines.push({ state: 'done', icon: PencilLine, text: t('Wrote search terms') })
  if (p.requests_planned === null) return lines
  if (!p.found) {
    if (live) lines.push({ state: 'running', icon: Search, text: t('Searching providers ({sent} of {n} queries)', { sent: p.requests_sent ?? 0, n: p.requests_planned }) })
    // Stopped before its count: what the answered requests already added is in the research, so it is shown as such.
    else lines.push(c.records ? { state: 'attention', icon: Search, text: t('The search stopped after {sent} of {n} queries. It had found {works} works in {records} records: {new} new, {already} already in this research', { sent: p.requests_sent ?? 0, n: p.requests_planned, works: c.new + c.already_here + c.removed_before, records: c.records, new: c.new, already: c.already_here }) }
      : { state: 'attention', icon: Search, text: t('The search stopped after {sent} of {n} queries; nothing was added', { sent: p.requests_sent ?? 0, n: p.requests_planned }) })
    return lines
  }
  lines.push({ state: 'done', icon: Search, text: [t('Found {works} works in {records} records: {new} new, {already} already in this research', { works: c.new + c.already_here + c.removed_before, records: c.records, new: c.new, already: c.already_here }),
    c.removed_before ? t('{n} removed before', { n: c.removed_before }) : ''].filter(Boolean).join(', ') })
  if (!p.screen_planned) return lines
  const screened = c.code_decided + c.model_result
  lines.push(p.summary ? { state: c.not_screened ? 'attention' : 'done', icon: BookOpen, text: t('Screened {screened} of {n} new works: {candidates} passed the abstract', { screened, n: p.screen_planned, candidates: c.candidates }) }
    : live ? { state: 'running', icon: BookOpen, text: t('Screening {n} new works', { n: p.screen_planned }) }
      : { state: 'attention', icon: BookOpen, text: t('Screened {screened} of {n} new works', { screened, n: p.screen_planned }) })
  return lines
}

// A request that did not succeed: the app's own refusals in its words, a provider's failure as the Search details say it.
const requestFailure: Record<string, string> = {
  openalex_budget_exhausted: 'OpenAlex daily budget used up; not sent', outcome_unknown: 'Sent, but no reply came back; not sent again',
  not_sent: 'Not sent', cancelled: 'Cancelled',
}
const failureText = (r: FollowupSearchRequest) => {
  const code = r.reason ?? r.status
  return requestFailure[code] ? `${providerName(r.provider_id)}: ${t(requestFailure[code])}` : serviceErrorSentence({ kind: serviceKind(code), service: providerName(r.provider_id) })
}

function FollowupSearchView({ turn, actions }: { turn: FollowupTurn; actions: FollowupTurnActions }) {
  const search = turn.search
  const last = search.runs[search.runs.length - 1]
  const offer = search.offered && <div className={`followup-search-offer${search.emphasis === 'suggested' ? ' is-suggested' : ''}`}>
    {search.emphasis === 'suggested' && <p>{t('This asks for works outside this research. A search adds what it finds as candidates; nothing is included until you include it.')}</p>}
    <Button size="sm" variant={search.emphasis === 'suggested' ? 'default' : 'outline'} disabled={actions.busy || actions.locked} onClick={() => actions.onSearch(turn.id)}>
      {search.attempt > 1 ? <RotateCw size={14} aria-hidden /> : <Search size={14} aria-hidden />}{t(search.attempt > 1 ? 'Try the search again' : 'Search for new works')}</Button>
  </div>
  if (!last) return offer || null
  const live = ACTIVE.has(last.status)
  const userPaused = last.status === 'paused' && last.pause_reason === 'user_requested'
  const failed = last.summary.requests.filter(r => r.status !== 'succeeded')
  return <div className="followup-search">
    <p className="followup-search-head"><Search size={14} aria-hidden />{t('Search for new works')}</p>
    <ol className="followup-steps">{searchSteps(last).map(line => <StepLine key={line.text} state={line.state} icon={line.icon}>{line.text}</StepLine>)}</ol>
    {failed.length > 0 && !live && <ul className="followup-search-failed">{failed.map(r => <li key={r.position}>{failureText(r)}</li>)}</ul>}
    {last.status === 'completed' && last.summary.counts.candidates > 0 && <p className="followup-note">
      <button type="button" className="link" onClick={e => actions.onShowCandidates(e.currentTarget)}>{t('Review the new candidates in Sources')}</button></p>}
    {!live && last.status !== 'completed' && <div className={`chat-note notice followup-notice ${userPaused ? 'is-warning' : 'is-error'}`}>
      {userPaused ? <Pause size={16} aria-hidden /> : <TriangleAlert size={16} aria-hidden />}
      <div className="notice-body">
        <p><b>{last.status === 'cancelled' ? t('The search was cancelled. Nothing it found was included.') : userPaused ? t('Paused after the current call.')
          : pauseReasonText(last.pause_reason, last.error) || t('The search stopped before it finished.')}</b></p>
        {last.status === 'paused' && <div className="notice-actions">
          <Button size="sm" disabled={actions.busy || actions.locked} onClick={() => actions.onControl(last.run_id, 'resume')}><Play size={14} aria-hidden />{t('Resume run')}</Button>
          <Button variant="outline" size="sm" className="notice-ghost" disabled={actions.busy} onClick={() => actions.onControl(last.run_id, 'cancel')}>{t('Cancel run')}</Button>
        </div>}
      </div>
    </div>}
    {!live && offer}
  </div>
}

// What a grouping's count covers (D66), on screen and in the copied text alike.
const coverageText = (groups: FollowupWorkGroups) => [
  t('Counted by DEIXIS: {classified} of the {sent} works whose passages were sent are in a group; this research includes {included}.', { classified: groups.classified_works, sent: groups.sent_works, included: groups.included_works }),
  groups.groups.reduce((n, g) => n + g.count, 0) > groups.classified_works ? t('A work can be in more than one group, so the counts add up to more.') : '',
].filter(Boolean).join(' ')
const GROUP_GAPS = [['ambiguous', 'Not settled by their passages'], ['insufficient_evidence', 'Their passages say nothing about this'],
  ['unclassified', 'Sent but not placed in a group'], ['table_not_sent', 'In the evidence table, but their passages were not sent to this answer']] as const
const groupsText = (groups: FollowupWorkGroups) => [
  ...groups.groups.flatMap(g => ['', `${g.label}: ${t('{n} works', { n: g.count })}`, ...g.works.map(w => `- ${workTitle(w)}${
    w.inference || w.citations.some(c => c.support_type !== 'source_stated') ? ` [${t('interpretation')}]` : ''}${
    w.citations.length ? ` (${w.citations.map(c => `"${c.anchor_text}"`).join('; ')})` : ''}${w.note ? ` — ${w.note}` : ''}`)]),
  '', coverageText(groups),
  ...GROUP_GAPS.filter(([part]) => groups[part].length > 0).flatMap(([part, heading]) => ['', `${t(heading)}:`,
    ...groups[part].map(w => `- ${workTitle(w)}${'note' in w && w.note ? ` — ${w.note}` : ''}`)]),
]

export function FollowupTurnView({ turn, sources, actions }: { turn: FollowupTurn; sources: Source[]; actions: FollowupTurnActions }) {
  const toast = useToast()
  const live = turn.status === 'pending' && ACTIVE.has(turn.run.status)
  const answer = turn.answer
  const claims = answer ? answer.claims.map(c => followupClaim(turn, c, sources)) : []
  // The works of each group (D66), each with its own chip into the Citation panel.
  const groupClaims = new Map(followupGroupClaims(turn).map(c => [c.label, followupClaim(turn, c, sources)]))
  const groups = answer?.work_groups ?? null
  // The chip names its first source by its key, else the numbers of the turn's cited passages in order.
  const numbers = new Map<string, number>()
  ;[...claims, ...groupClaims.values()].forEach(c => c.evidence.forEach(e => { if (!numbers.has(e.passage_id)) numbers.set(e.passage_id, numbers.size + 1) }))
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
      ...(groups ? groupsText(groups) : []),
      ...(answer?.unanswered_aspects.length ? ['', `${t('Not answered by these passages')}:`, ...answer.unanswered_aspects.map(a => `- ${a}`)] : [])].join('\n')
    try { await writeClipboard(text); toast('success', t('Follow-up answer copied to clipboard.')) }
    catch { toast('error', t('Could not copy to the clipboard.')) }
  }
  const userPaused = turn.run.status === 'paused' && turn.run.pause_reason === 'user_requested'
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
        {claim.support_type === 'analyst_inference' && <span className="support-badge is-inference">{t('interpretation')}</span>}
        {chip(claim)}</span>)}</p></div>}
      {groups && <div className="followup-groups">
        {groups.groups.map((group, g) => <div className="followup-group" key={group.label}>
          <p className="followup-group-head"><b>{group.label}</b> · {t('{n} works', { n: group.count })}</p>
          <ul>{group.works.map(work => { const claim = groupClaims.get(`g${g + 1}:${work.work_id}`)
            return <li key={work.work_id}><MathText text={workTitle(work)} />
              {claim?.support_type === 'analyst_inference' && <span className="support-badge is-inference">{t('interpretation')}</span>} {claim && chip(claim)}
              {work.note && <> — <MathText text={work.note} /></>}</li> })}</ul>
        </div>)}
        <p className="followup-note">{coverageText(groups)}</p>
        {GROUP_GAPS.filter(([part]) => groups[part].length > 0).map(([part, heading]) => <div className="followup-gaps" key={part}><p>{t(heading)}</p>
            <ul>{groups[part].map(work => <li key={work.work_id}><MathText text={workTitle(work)} />{'note' in work && work.note ? <> — <MathText text={work.note} /></> : null}</li>)}</ul></div>)}
      </div>}
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
    {!live && turn.status !== 'pending' && (claims.length > 0 || groups) && <div className="followup-acts">
      {(claims.length > 0 || groups) && <Button variant="ghost" size="icon-sm" className="answer-ib" aria-label={t('Copy follow-up answer')} title={t('Copy follow-up answer')} onClick={() => { void copy() }}><Copy size={16} aria-hidden /></Button>}
    </div>}
    {!live && turn.status !== 'pending' && <FollowupSearchView turn={turn} actions={actions} />}
  </section>
}
