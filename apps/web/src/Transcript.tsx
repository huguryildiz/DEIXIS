import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, Check, ChevronDown, ChevronRight, LoaderCircle, Minus, Search, TriangleAlert } from 'lucide-react'
import type { ResearchView, Run } from './api'
import { pauseReasonText, providerName, runStatusLabels, stepLabel } from './labels'
import { ConnectionIcon } from './connectionIcons'
import { t, uiLocale } from './i18n'

// The research page as a conversation: the question, then one DEIXIS turn per run whose steps appear as they happen.
// The page's event stream refreshes the view; a one-second clock keeps running durations moving between events.
// Run controls stay in the run card above the tabs, so they are reachable from every tab.

type PhaseKey = 'plan' | 'search' | 'screen' | 'pdf' | 'answer' | 'review'
type PhaseState = 'done' | 'running' | 'attention' | 'waiting' | 'skipped'
type Step = NonNullable<Run['steps']>[number]

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
// Title while running, once done, and before the phase starts or when it is not run.
const titles: Record<PhaseKey, [string, string, string]> = {
  plan: ['Planning the searches', 'Planned the searches', 'Search plan'],
  search: ['Searching the providers', 'Searched the providers', 'Provider searches'],
  screen: ['Screening the candidates', 'Screened the candidates', 'Screening'],
  pdf: ['Downloading open-access PDFs', 'Downloaded open-access PDFs', 'Open-access PDFs'],
  answer: ['Writing the answer', 'Wrote the answer', 'Source-linked answer'],
  review: ['Reviewing the claims', 'Reviewed the claims', 'Claim review'],
}
const discoveryHeadings: Record<string, string> = { active: 'Searching and screening', completed: 'Ran search & screening', paused: 'Search & screening paused', failed: 'Search & screening failed', cancelled: 'Search & screening cancelled' }
const answerHeadings: Record<string, string> = { active: 'Generating the answer', completed: 'Ran answer generation', paused: 'Answer generation paused', failed: 'Answer generation failed', cancelled: 'Answer generation cancelled' }
// The run's stage names the phase it has reached before that phase records its first step.
const stagePhases: Record<string, PhaseKey> = { screening: 'screen', inspection: 'pdf', answer: 'answer', claim_check: 'review' }
const fetchReasons: Record<string, string> = { fetch_http_error: 'server refused', fetch_timeout: 'timed out', fetch_too_large: 'file too large', fetch_not_pdf: 'not a PDF', fetch_blocked_url: 'address not allowed', fetch_failed: 'connection failed' }

function phaseOf(kind: string): PhaseKey | null {
  if (kind === 'model:search_plan') return 'plan'
  if (kind.startsWith('provider_search')) return 'search'
  if (kind === 'model:screening') return 'screen'
  if (kind === 'fetch_pdf') return 'pdf'
  if (kind === 'model:grounded_answer') return 'answer'
  if (kind === 'model:answer_review') return 'review'
  return null
}

const durationText = (seconds: number) => (seconds < 60 ? t('{s} s', { s: seconds }) : t('{m} min {s} s', { m: Math.floor(seconds / 60), s: seconds % 60 }))
const secondsBetween = (from: string, to: number) => Math.max(0, Math.round((to - Date.parse(from)) / 1000))
const present = (values: (string | null)[]) => values.filter((v): v is string => Boolean(v)).sort()
const troubled = (s: Step) => s.status === 'failed' || s.status === 'outcome_unknown'
const plural = (n: number, one: string, many: string, vars: Record<string, string | number> = {}) => t(n === 1 ? one : many, { n, ...vars })
const compact = (n: number) => new Intl.NumberFormat(uiLocale(), { notation: 'compact', maximumFractionDigits: 1 }).format(n)

type ModelText = (model: string | null, effort: string | null) => string

export function Transcript({ view, emptyText, latestAnswer, modelText }: { view: ResearchView; emptyText: string; latestAnswer: ReactNode; modelText: ModelText }) {
  const runs = [...view.runs].reverse()  // the view lists the newest run first
  const active = runs.some(r => ACTIVE.has(r.status))
  const end = useRef<HTMLDivElement>(null)
  const [atEnd, setAtEnd] = useState(true)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const node = end.current
    if (!node) return
    const observer = new IntersectionObserver(([entry]) => setAtEnd(entry.isIntersecting))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return <div className="chat">
    <div className="chat-user">{view.scope.question}</div>
    {runs.map((run, i) => <RunTurn key={run.id} run={run} view={view} now={now} latest={i === runs.length - 1} modelText={modelText}>
      {view.answers[0]?.run_id === run.id ? latestAnswer : null}
    </RunTurn>)}
    {!runs.length && <p className="chat-say">{emptyText}</p>}
    <div ref={end} className="chat-end" />
    {active && !atEnd && <button type="button" className="chat-jump" onClick={() => end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })}><ArrowDown size={15} aria-hidden />{t('Jump to latest')}</button>}
  </div>
}

function RunTurn({ run, view, now, latest, modelText, children }: { run: Run; view: ResearchView; now: number; latest: boolean; modelText: ModelText; children: ReactNode }) {
  const active = ACTIVE.has(run.status)
  const [open, setOpen] = useState<boolean | null>(null)
  const [queriesOpen, setQueriesOpen] = useState(true)
  // A finished run folds away once something follows it; the latest search stays open so its queries can be read.
  const expanded = open ?? (run.status !== 'completed' || (latest && run.kind === 'discovery'))
  const clock = active ? Math.max(now, Date.parse(run.updated_at)) : Date.parse(run.updated_at)

  const steps = run.steps ?? []
  const order: PhaseKey[] = run.kind === 'discovery' ? ['plan', 'search', 'screen'] : ['pdf', 'answer', ...(view.reviewer.model ? ['review' as const] : [])]
  const groups = order.map(key => steps.filter(s => phaseOf(s.kind) === key))
  const reached = Math.max(order.indexOf(stagePhases[run.stage]), ...groups.map((group, i) => (group.length ? i : -1)))
  const searches = view.search_runs.filter(s => s.run_id === run.id)
  const answer = view.answers.find(a => a.run_id === run.id)
  const started = present(steps.map(s => s.started_at))[0] ?? run.created_at
  const unknownSteps = steps.filter(s => s.status === 'outcome_unknown')
  // A failed search no longer stops the run (D18); name what is missing so the results are not read as complete.
  const failedSearches = [...new Set(steps.filter(s => s.kind.startsWith('provider_search') && troubled(s))
    .map(s => `${providerName(s.kind.split(':')[1] ?? '')} (${t((s.error_code ?? 'failed').replace('_', ' '))})`))]
  const runningSearch = groups[order.indexOf('search')]?.find(s => s.status === 'running')

  const stateOf = (i: number): PhaseState => {
    if (i < reached) return groups[i].length ? 'done' : 'skipped'
    if (i === reached) return active ? 'running' : run.status === 'completed' ? 'done' : 'attention'
    if (active && reached < 0 && i === 0 && run.status !== 'queued') return 'running'
    return active || run.status === 'paused' ? 'waiting' : 'skipped'
  }

  const title = (key: PhaseKey, state: PhaseState, group: Step[]) => {
    const finished = searches.filter(s => s.status === 'completed' || s.status === 'zero_results').length
    if (state === 'done' && key === 'search') return plural(finished, 'Conducted {n} search', 'Conducted {n} searches')
    if (state === 'done' && key === 'pdf') return plural(group.filter(s => s.status === 'succeeded').length, 'Downloaded {n} open-access PDF', 'Downloaded {n} open-access PDFs')
    if (state === 'done' && key === 'review' && answer?.review?.status === 'completed') return plural(answer.review.reviews.length, 'Reviewed {n} claim', 'Reviewed {n} claims')
    const [running, done, idle] = titles[key]
    return t(state === 'running' || state === 'attention' ? running : state === 'done' ? done : idle)
  }

  const detail = (key: PhaseKey, state: PhaseState, group: Step[]): string => {
    const attempt = Math.max(0, ...group.map(s => s.attempt))
    const attemptText = attempt > 1 && state === 'running' ? t('attempt {n}', { n: attempt }) : ''
    if (state === 'waiting') return t('Waiting')
    if (state === 'skipped') return t(key === 'pdf' && run.status === 'completed' ? 'No open-access PDF to download' : run.status === 'completed' ? 'Not needed' : 'Not run')
    switch (key) {
      case 'search': {
        const records = searches.reduce((sum, s) => sum + (s.status === 'completed' ? s.result_count : 0), 0)
        return searches.length ? plural(records, '{n} record', '{n} records') : ''
      }
      case 'screen': {
        const done = group.filter(s => s.status === 'succeeded').length
        if (state === 'running') return done ? plural(done, '{n} batch done', '{n} batches done') : ''
        return t('{included} included · {excluded} excluded · {pending} undecided', { included: view.counts.included, excluded: view.counts.excluded, pending: view.counts.pending })
      }
      case 'pdf': {
        const reasons = new Map<string, number>()
        group.filter(troubled).forEach(s => { const reason = t(fetchReasons[s.error_code ?? ''] ?? 'connection failed'); reasons.set(reason, (reasons.get(reason) ?? 0) + 1) })
        const failed = [...reasons.values()].reduce((a, b) => a + b, 0)
        const ok = group.filter(s => s.status === 'succeeded').length
        const parts = [state === 'running' && group.length ? plural(ok, '{n} downloaded', '{n} downloaded') : '', failed ? t('{n} not downloaded ({reasons})', { n: failed, reasons: [...reasons].map(([reason, n]) => `${n} ${reason}`).join(', ') }) : '']
        return parts.filter(Boolean).join(' · ')
      }
      case 'answer':
        if (state !== 'done') return attemptText
        if (answer?.status === 'structurally_valid' && answer.inputs_given) return t('{claims} claims · {passages} passages from {sources} sources', { claims: answer.claims.length, passages: answer.inputs_given.passages, sources: answer.inputs_given.sources })
        return answer ? t(answer.status.replaceAll('_', ' ')) : ''
      case 'review':
        return state === 'done' && answer?.review && answer.review.status !== 'completed' ? t('No usable review') : attemptText
      default:
        return attemptText
    }
  }

  const phaseSeconds = (group: Step[], state: PhaseState) => {
    const starts = present(group.map(s => s.started_at))
    if (!starts.length) return null
    const ends = present(group.map(s => s.finished_at))
    return secondsBetween(starts[0], state === 'running' || !ends.length ? clock : Date.parse(ends[ends.length - 1]))
  }

  // The model role that runs each model phase, as chosen for this research; the answer shows the model Codex reported.
  const scope = view.scope
  const literature = { role: 'Literature', model: scope.literature_model ?? scope.requested_model, effort: scope.literature_model ? scope.literature_reasoning_effort : scope.reasoning_effort }
  const agents: Partial<Record<PhaseKey, { role: string; model: string | null; effort: string | null }>> = {
    plan: literature, screen: literature,
    answer: { role: 'Answer', model: answer?.model?.resolved_model ?? answer?.model?.requested_model ?? scope.requested_model, effort: scope.reasoning_effort },
    review: { role: 'Reviewer', model: answer?.review?.model?.resolved_model ?? view.reviewer.model, effort: view.reviewer.reasoning_effort },
  }
  const providers = new Intl.ListFormat(uiLocale(), { type: 'conjunction' }).format(view.scope.providers.map(providerName))
  // Worded as what happened, so it reads apart from the run card's "Search & screening · Completed" status above the tabs.
  const outcome = active ? 'active' : run.status
  const label = t((run.kind === 'discovery' ? discoveryHeadings : answerHeadings)[outcome] ?? runStatusLabels[run.status])
  const olderRevision = run.scope_revision !== view.research.current_scope_revision
  return <section className="chat-turn">
    <p className="chat-say">{run.kind === 'discovery' ? t('Plan: search {providers}, then screen the candidates.', { providers }) : t('Plan: download the open-access PDFs of the included sources, then write a source-linked answer.')}</p>
    <div className="chat-group">
      <button type="button" className="chat-toggle" aria-expanded={expanded} onClick={() => setOpen(!expanded)}>
        {expanded ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
        <span>{label}{olderRevision ? ` ${t('· for question revision {n}', { n: run.scope_revision })}` : ''}</span>
        {active && <LoaderCircle size={14} className="chat-spin" aria-hidden />}
        <time>{durationText(secondsBetween(started, clock))}</time>
      </button>
      {expanded && <ol className="chat-steps">{order.map((key, i) => {
        const state = stateOf(i)
        const group = groups[i]
        const seconds = phaseSeconds(group, state)
        const text = detail(key, state, group)
        const hasQueries = key === 'search' && (searches.length > 0 || Boolean(runningSearch && active))
        return <li key={key} className={`chat-step is-${state}`}>
          <div className="chat-step-line">
            <span className="chat-step-icon" role="img" aria-label={t(state === 'done' ? 'Done' : state === 'running' ? 'In progress' : state === 'attention' ? 'Stopped here' : state === 'waiting' ? 'Waiting' : 'Not run')}>
              {state === 'done' ? <Check size={13} strokeWidth={2.5} /> : state === 'running' ? <LoaderCircle size={14} className="chat-spin" /> : state === 'attention' ? <TriangleAlert size={13} /> : state === 'skipped' ? <Minus size={13} /> : null}
            </span>
            {hasQueries
              ? <button type="button" className="chat-step-title" aria-expanded={queriesOpen} onClick={() => setQueriesOpen(!queriesOpen)}>{title(key, state, group)}{queriesOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}</button>
              : <span className="chat-step-title">{title(key, state, group)}</span>}
            {agents[key]?.model && state !== 'skipped' && <span className={`agent-chip${state === 'running' ? ' is-running' : ''}`} title={t('Model that runs this step')}>
              <ConnectionIcon id={scope.model_connection} />{[t(agents[key].role), modelText(agents[key].model, agents[key].effort)].filter(Boolean).join(' · ')}
            </span>}
            {text && <small>{text}</small>}
            <time>{seconds === null ? '' : durationText(seconds)}</time>
          </div>
          {hasQueries && queriesOpen && <div className="query-box">
            {searches.map(s => {
              const ok = s.status === 'completed' || s.status === 'zero_results'
              return <div key={s.id} className={`query-row${ok ? '' : ' is-attention'}`} title={s.query_text}>
                <Search size={14} aria-hidden />
                <span className="query-text">{s.query_text}</span>
                <span className="query-meta"><ConnectionIcon id={s.provider} />{providerName(s.provider)} · {ok ? t('{count} of {total}', { count: s.result_count, total: s.provider_total === null ? '?' : compact(s.provider_total) }) : t(s.status.replace('_', ' '))}</span>
              </div>
            })}
            {runningSearch && active && <div className="query-row is-running">
              <LoaderCircle size={14} className="chat-spin" aria-hidden />
              <span className="query-text">{t('{provider} · searching', { provider: providerName(runningSearch.kind.split(':')[1] ?? '') })}</span>
            </div>}
          </div>}
        </li>
      })}</ol>}
    </div>

    {failedSearches.length > 0 && run.status !== 'paused' && <div className="chat-note"><p>{t('Some searches did not complete: {list}. The results of the other searches are used; search again to retry them.', { list: failedSearches.join(', ') })}</p></div>}
    {run.status === 'paused' && <div className="chat-note is-warning">
      <p>{pauseReasonText(run.pause_reason)}</p>
      {unknownSteps.length > 0 && <p>{t('Unfinished: {steps}. Resuming repeats it; a repeated model call counts against your account usage.', { steps: unknownSteps.map(s => stepLabel(s.kind, s.operation_key)).join(', ') })}</p>}
    </div>}
    {(run.status === 'failed' || run.status === 'cancelled') && run.pause_reason && <div className="chat-note is-warning"><p>{pauseReasonText(run.pause_reason)}</p></div>}
    {run.kind === 'discovery' && run.status === 'completed' && latest && !answer && <p className="chat-say">{t(view.counts.included === 1 ? 'Found {unique} unique works; {included} is included. Check the Sources tab, then generate an answer.' : 'Found {unique} unique works; {included} are included. Check the Sources tab, then generate an answer.', { unique: view.counts.unique, included: view.counts.included })}</p>}
    {children}
    {!children && answer && run.kind === 'answer' && <p className="chat-say is-muted">{t('An earlier answer: {status}.', { status: t(answer.status.replaceAll('_', ' ')) })}</p>}
  </section>
}
