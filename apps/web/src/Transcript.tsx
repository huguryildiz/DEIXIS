import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, Check, ChevronDown, ChevronRight, LoaderCircle, Minus, Search, Sparkles, TriangleAlert } from 'lucide-react'
import type { ResearchView, Run, Verdict } from './api'
import { fetchReasonText, pauseReasonText, providerName, runStatusLabels, stepLabel, verdictLabels } from './labels'
import { ConnectionIcon } from './connectionIcons'
import { t, uiLocale } from './i18n'

// The research page as a conversation: the question, then one DEIXIS turn per run whose steps appear as they happen.
// The page's event stream refreshes the view; a one-second clock keeps running durations moving between events.
// Run controls stay in the run card above the tabs, so they are reachable from every tab.

type PhaseKey = 'plan' | 'search' | 'screen' | 'pdf' | 'semantic' | 'answer' | 'review'
type PhaseState = 'done' | 'running' | 'attention' | 'waiting' | 'skipped'
type Step = NonNullable<Run['steps']>[number]

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
// Title while running, once done, and before the phase starts or when it is not run.
const titles: Record<PhaseKey, [string, string, string]> = {
  plan: ['Planning the searches', 'Planned the searches', 'Search plan'],
  search: ['Searching the providers', 'Searched the providers', 'Provider searches'],
  screen: ['Screening the candidates', 'Screened the candidates', 'Screening'],
  pdf: ['Downloading open-access PDFs', 'Downloaded open-access PDFs', 'Open-access PDFs'],
  semantic: ['Preparing semantic search', 'Prepared semantic search', 'Semantic search'],
  answer: ['Writing the answer', 'Wrote the answer', 'Source-linked answer'],
  review: ['Reviewing the claims', 'Reviewed the claims', 'Claim review'],
}
const discoveryHeadings: Record<string, string> = { active: 'Searching and screening', completed: 'Ran search & screening', paused: 'Search & screening paused', failed: 'Search & screening failed', cancelled: 'Search & screening cancelled' }
const answerHeadings: Record<string, string> = { active: 'Generating the answer', completed: 'Ran answer generation', paused: 'Answer generation paused', failed: 'Answer generation failed', cancelled: 'Answer generation cancelled' }
// The run's stage names the phase it has reached before that phase records its first step.
const stagePhases: Record<string, PhaseKey> = { screening: 'screen', inspection: 'pdf', answer: 'answer', claim_check: 'review' }
const basisLabels: Record<string, string> = { metadata_only: 'metadata only', title_only: 'title only', title_and_abstract: 'title and abstract' }

function phaseOf(kind: string): PhaseKey | null {
  if (kind === 'model:search_plan') return 'plan'
  if (kind.startsWith('provider_search')) return 'search'
  if (kind === 'model:screening') return 'screen'
  if (kind === 'fetch_pdf' || kind === 'pdf_other_copy') return 'pdf'
  if (kind.startsWith('embedding:')) return 'semantic'
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
const tally = (values: string[]) => { const counts = new Map<string, number>(); values.forEach(v => counts.set(v, (counts.get(v) ?? 0) + 1)); return [...counts] }
// Each connection reports its token counts under its own key; the figure is left out when neither is there.
function totalTokens(usage: unknown): number | null {
  const counts = usage as { total_tokens?: unknown; totalTokenCount?: unknown } | null
  const total = counts?.total_tokens ?? counts?.totalTokenCount
  return typeof total === 'number' ? total : null
}

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
  // The plan summary and its concept list share one disclosure control.
  const [conceptsOpen, setConceptsOpen] = useState(true)
  // A finished run folds away once something follows it; the latest search stays open so its queries can be read.
  const expanded = open ?? (run.status !== 'completed' || (latest && run.kind === 'discovery'))
  const clock = active ? Math.max(now, Date.parse(run.updated_at)) : Date.parse(run.updated_at)

  const steps = run.steps ?? []
  const order: PhaseKey[] = run.kind === 'discovery' ? ['plan', 'search', 'screen'] : ['pdf', 'semantic', 'answer', ...(view.reviewer.model ? ['review' as const] : [])]
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
  const plan = run.plan
  // The screening the run itself proposed on, and the sources the answer run reads.
  const screened = view.sources.filter(s => s.found_in_revision === run.scope_revision)
  const included = view.sources.filter(s => s.selection.state === 'included')
  // The similarity step belongs to no phase of its own; the screening phase reports it.
  const similarity = steps.find(s => s.kind.startsWith('similarity:'))
  const rationaleOf = (provider: string, query: string) => plan?.queries.find(q => q.provider_id === provider && q.query_text === query)?.rationale ?? ''

  const stateOf = (i: number): PhaseState => {
    const hasTrouble = groups[i].some(troubled)
    if (groups[i].some(step => step.status === 'running')) return 'running'
    if (i < reached) return hasTrouble ? 'attention' : groups[i].length ? 'done' : 'skipped'
    if (i === reached) return active ? 'running' : hasTrouble ? 'attention' : run.status === 'completed' ? 'done' : 'attention'
    if (active && reached < 0 && i === 0 && run.status !== 'queued') return 'running'
    return active || run.status === 'paused' ? 'waiting' : 'skipped'
  }

  const title = (key: PhaseKey, state: PhaseState, group: Step[]) => {
    const finished = searches.filter(s => s.status === 'completed' || s.status === 'zero_results').length
    if (state === 'done' && key === 'search') return plural(finished, 'Conducted {n} search', 'Conducted {n} searches')
    if (state === 'done' && key === 'pdf') return plural(group.filter(s => s.status === 'succeeded').length, 'Downloaded {n} open-access PDF', 'Downloaded {n} open-access PDFs')
    if (state === 'done' && key === 'review' && answer?.review?.status === 'completed') return plural(answer.review.reviews.length, 'Reviewed {n} claim', 'Reviewed {n} claims')
    const [running, done, idle] = titles[key]
    return t(state === 'running' ? running : state === 'done' ? done : idle)
  }

  const detail = (key: PhaseKey, state: PhaseState, group: Step[]): string => {
    const attempt = Math.max(0, ...group.map(s => s.attempt))
    const attemptText = attempt > 1 && state === 'running' ? t('attempt {n}', { n: attempt }) : ''
    if (state === 'waiting') return t('Waiting')
    if (state === 'skipped') return t(key === 'pdf' && run.status === 'completed' ? 'No open-access PDF to download' : key === 'semantic' && run.status === 'completed' ? 'Not used' : run.status === 'completed' ? 'Not needed' : 'Not run')
    switch (key) {
      case 'plan': {
        if (state !== 'done' || !plan) return attemptText
        const synonyms = plan.concepts.reduce((sum, c) => sum + c.synonyms.length, 0)
        return [plural(plan.concepts.length, '{n} concept', '{n} concepts'), plural(synonyms, '{n} synonym', '{n} synonyms')].join(' · ')
      }
      case 'search': {
        if (!searches.length) return ''
        // Per provider: the records taken, and the total the provider reported when it is larger than what was taken.
        const perProvider = new Map<string, { taken: number; total: number | null }>()
        searches.forEach(s => {
          const seen = perProvider.get(s.provider) ?? { taken: 0, total: null }
          perProvider.set(s.provider, { taken: seen.taken + (s.status === 'completed' ? s.result_count : 0),
            total: s.provider_total === null ? seen.total : (seen.total ?? 0) + s.provider_total })
        })
        const found = searches.reduce((sum, s) => sum + (s.status === 'completed' ? s.result_count : 0), 0)
        // One provider: the query rows below already name it with its counts, so the line keeps only the total.
        const parts = perProvider.size > 1
          ? [...perProvider].map(([id, { taken, total }]) => `${providerName(id)} ${total !== null && total > taken ? t('{count} of {total}', { count: taken, total: compact(total) }) : taken}`)
          : [plural(found, '{n} record', '{n} records')]
        // This run's own records against the works kept for its question revision; the research-wide counts would mix in older runs.
        const unique = new Set(screened.map(s => s.work_id)).size  // versions of one work count once
        if (state === 'done' && found && found !== unique) parts.push(t('{found} found → {unique} unique', { found, unique }))
        return parts.join(' · ')
      }
      case 'screen': {
        const done = group.filter(s => s.status === 'succeeded').length
        if (state === 'running') return done ? plural(done, '{n} batch done', '{n} batches done') : ''
        return t('{included} included · {excluded} excluded · {pending} undecided', { included: view.counts.included, excluded: view.counts.excluded, pending: view.counts.pending })
      }
      case 'pdf': {
        // One outcome per source: a copy found after its link refused counts as downloaded, not as a failure.
        const outcomes = new Map<string, Step>()
        group.forEach(s => { const svid = s.operation_key.split(':')[1]; if (outcomes.get(svid)?.status !== 'succeeded') outcomes.set(svid, s) })
        const reasons = tally([...outcomes.values()].filter(troubled).map(s => fetchReasonText(s.error_code, (s.error as { http_status?: number } | null)?.http_status)))
        const failed = reasons.reduce((sum, [, n]) => sum + n, 0)
        const ok = group.filter(s => s.status === 'succeeded')
        const pages = ok.reduce((sum, s) => sum + (s.output?.page_count ?? 0), 0)
        const parts = [state === 'running' && group.length ? plural(ok.length, '{n} downloaded', '{n} downloaded') : '',
          state === 'done' && pages ? t('{pages} pages · {passages} passages', { pages, passages: ok.reduce((sum, s) => sum + (s.output?.passage_count ?? 0), 0) }) : '',
          failed ? t('{n} not downloaded ({reasons})', { n: failed, reasons: reasons.map(([reason, n]) => `${n} ${reason}`).join(', ') }) : '']
        return parts.filter(Boolean).join(' · ')
      }
      case 'semantic': {
        if (state === 'running') return attemptText
        if (state === 'attention') return t('Unavailable · continued with keyword search')
        const output = group.find(s => s.status === 'succeeded')?.output
        return output?.passages !== undefined && output.embedded !== undefined
          ? t('{passages} passages ranked · {embedded} newly embedded', { passages: output.passages, embedded: output.embedded })
          : ''
      }
      case 'answer': {
        if (state !== 'done') return attemptText
        if (answer?.status !== 'structurally_valid' || !answer.inputs_given) return answer ? t(answer.status.replaceAll('_', ' ')) : ''
        const cited = new Set(answer.claims.flatMap(c => c.evidence.map(e => e.passage_id))).size
        return t('{claims} claims · {cited} of {passages} passages cited · {sources} sources', { claims: answer.claims.length, cited, passages: answer.inputs_given.passages, sources: answer.inputs_given.sources })
      }
      case 'review': {
        if (state !== 'done' || !answer?.review) return attemptText
        if (answer.review.status !== 'completed') return t('No usable review')
        return tally(answer.review.reviews.map(r => r.verdict)).map(([verdict, n]) => `${n} ${t(verdictLabels[verdict as Verdict])}`).join(' · ')
      }
      default:
        return attemptText
    }
  }

  // What the finished phase found, from the counts and fields the model already wrote; nothing is narrated for it.
  const report = (key: PhaseKey, state: PhaseState, group: Step[]): ReactNode => {
    if (state !== 'done') return null
    switch (key) {
      case 'plan': {
        if (!plan) return null
        return <>
          <p className="chat-phase-summary">{plan.question_interpretation}</p>
          <p>{plan.search_rationale}</p>
          {plan.scope_boundaries.length > 0 && <p className="chat-scope-note"><span>{t('Scope limits')}</span>{plan.scope_boundaries.join(' · ')}</p>}
        </>
      }
      case 'screen': {
        const basis = tally(present(screened.map(s => s.selection.proposal_basis)))
        const changed = screened.filter(s => s.selection.origin === 'user' && s.selection.proposal !== null).length
        const lines = [
          basis.length ? t('Judged from: {list}', { list: basis.map(([b, n]) => `${n} ${t(basisLabels[b] ?? b)}`).join(' · ') }) : '',
          changed ? plural(changed, 'You changed {n} proposal', 'You changed {n} proposals') : '',
        ].filter(Boolean)
        return <>
          {similarity && <p>{similarity.status === 'succeeded'
            ? plural(similarity.output?.sources ?? 0, 'Ranked {n} source by similarity ({model})', 'Ranked {n} sources by similarity ({model})', { model: similarity.output?.model ?? similarity.kind.split(':')[1] ?? '' })
            : t('Similarity unavailable; ordered by search position')}</p>}
          {lines.length > 0 && <p>{lines.join(' · ')}</p>}
          {run.screening_notes && <p>{run.screening_notes}</p>}
        </>
      }
      case 'pdf': {
        const candidates = included.flatMap(s => s.access.pdf_candidates)
        const verified = candidates.filter(c => c.identity_status === 'doi_verified' || c.identity_status === 'title_verified').length
        const abstractOnly = included.filter(s => !s.access.assets.length && s.access.abstract_passage_id).length
        const lines = [
          candidates.length ? t('PDF candidates: {list}', { list: tally(candidates.map(c => c.provider)).map(([id, n]) => `${providerName(id)} ${n}`).join(' · ') }) : '',
          verified ? t('{n} identity verified', { n: verified }) : '',
          abstractOnly ? plural(abstractOnly, '{n} source read from abstract only', '{n} sources read from abstract only') : '',
        ].filter(Boolean)
        return lines.length ? <p>{lines.join(' · ')}</p> : null
      }
      case 'answer': {
        if (answer?.status !== 'structurally_valid') return null
        const stated = answer.claims.filter(c => c.support_type === 'source_stated').length
        const lines = [
          t('{stated} source-stated · {inferred} inferred', { stated, inferred: answer.claims.length - stated }),
          t('cited {cited} of {included} included sources', { cited: new Set(answer.claims.flatMap(c => c.evidence.map(e => e.source_version_id))).size, included: answer.inputs_given?.sources ?? 0 }),
          answer.unanswered_aspects.length ? plural(answer.unanswered_aspects.length, '{n} aspect not answered', '{n} aspects not answered') : '',
          answer.limitations.length ? plural(answer.limitations.length, '{n} limitation', '{n} limitations') : '',
        ].filter(Boolean)
        return <>
          <p>{lines.join(' · ')}</p>
          {Math.max(0, ...group.map(s => s.attempt)) > 1 && <p>{t('First output failed validation; repaired once.')}</p>}
        </>
      }
      default:
        return null
    }
  }

  const phaseSeconds = (group: Step[], state: PhaseState) => {
    const starts = present(group.map(s => s.started_at))
    if (!starts.length) return null
    const ends = present(group.map(s => s.finished_at))
    return secondsBetween(starts[0], state === 'running' || !ends.length ? clock : Date.parse(ends[ends.length - 1]))
  }

  // The model role that runs each model phase, as chosen for this research; the answer shows the model its connection reported.
  const scope = view.scope
  const literature = { role: 'Literature', connection: scope.literature_model ? scope.literature_connection ?? scope.model_connection : scope.model_connection,
    model: scope.literature_model ?? scope.requested_model, effort: scope.literature_model ? scope.literature_reasoning_effort : scope.reasoning_effort }
  const embeddingStep = steps.find(s => s.kind.startsWith('embedding:'))
  const embeddingStoredModel = embeddingStep?.kind.slice('embedding:'.length) ?? ''
  const embeddingParts = embeddingStoredModel.split(':')
  const embeddingConnections = new Set(['openai', 'ollama', 'lm_studio'])
  const embeddingConnection = embeddingConnections.has(embeddingParts[0]) ? embeddingParts[0] : 'gemini'
  const embeddingModel = embeddingConnections.has(embeddingParts[0]) ? embeddingParts.slice(1).join(':') : embeddingStoredModel
  const embeddingProviders: Record<string, string> = { gemini: 'Gemini', openai: 'OpenAI', ollama: 'Ollama', lm_studio: 'LM Studio' }
  const agents: Partial<Record<PhaseKey, { role: string; connection: string; model: string | null; effort: string | null }>> = {
    plan: literature, screen: literature,
    semantic: embeddingStep ? { role: embeddingProviders[embeddingConnection], connection: embeddingConnection, model: embeddingModel, effort: null } : undefined,
    answer: { role: 'Answer', connection: answer?.model?.connection ?? scope.model_connection, model: answer?.model?.resolved_model ?? answer?.model?.requested_model ?? scope.requested_model, effort: scope.reasoning_effort },
    review: { role: 'Reviewer', connection: answer?.review?.model?.connection ?? view.reviewer.connection ?? scope.model_connection, model: answer?.review?.model?.resolved_model ?? view.reviewer.model, effort: view.reviewer.reasoning_effort },
  }
  const providers = new Intl.ListFormat(uiLocale(), { type: 'conjunction' }).format(view.scope.providers.map(providerName))
  // Worded as what happened, so it reads apart from the run card's "Search & screening · Completed" status above the tabs.
  const outcome = active ? 'active' : run.status
  const label = t((run.kind === 'discovery' ? discoveryHeadings : answerHeadings)[outcome] ?? runStatusLabels[run.status])
  const olderRevision = run.scope_revision !== view.research.current_scope_revision
  const tokens = totalTokens(answer?.model?.token_usage)
  // What the run spent against what it was allowed; the token figure is the answer step's own, and no cost is estimated.
  const spend = [t('Model calls {calls}/{limit}', { calls: run.usage.model_calls ?? 0, limit: run.budget.max_model_calls ?? 0 }),
    t('provider requests {requests}/{limit}', { requests: run.usage.provider_requests ?? 0, limit: run.budget.max_provider_requests ?? 0 }),
    ...(tokens === null ? [] : [t('{n} answer tokens', { n: compact(tokens) })])].join(' · ')
  return <section className="chat-turn">
    <div className={`chat-group${active ? ' is-active' : ''}`}>
      <button type="button" className="chat-toggle" aria-expanded={expanded} onClick={() => setOpen(!expanded)}>
        {expanded ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
        <span className={active ? 'shimmer-text' : undefined}>{label}{olderRevision ? ` ${t('· for question revision {n}', { n: run.scope_revision })}` : ''}</span>
        {active && <LoaderCircle size={14} className="chat-spin" aria-hidden />}
        <time>{durationText(secondsBetween(started, clock))}</time>
      </button>
      {expanded && <>
        {latest && <div className="chat-run-plan" role="note">
          <Sparkles size={14} strokeWidth={1.8} aria-hidden />
          <div><p className="chat-run-plan-title">{run.kind === 'discovery' ? t('Search {providers}, then screen the candidates.', { providers }) : t('Download the open-access PDFs of the included sources, then write a source-linked answer.')}</p></div>
        </div>}
        {run.status !== 'queued' && <details className="chat-run-meta"><summary>{t('Run details')}</summary><p>{spend}</p></details>}
        <ol className="chat-steps">{order.map((key, i) => {
        const state = stateOf(i)
        const group = groups[i]
        const seconds = phaseSeconds(group, state)
        const text = detail(key, state, group)
        const hasQueries = key === 'search' && (searches.length > 0 || Boolean(runningSearch && active))
        const hasConcepts = key === 'plan' && state === 'done' && Boolean(plan?.concepts.length)
        const listOpen = hasQueries ? queriesOpen : conceptsOpen
        const note = report(key, state, group)
        return <li key={key} className={`chat-step is-${state}`}>
          <div className="chat-step-line">
            <span className="chat-step-icon" role="img" aria-label={t(state === 'done' ? 'Done' : state === 'running' ? 'In progress' : state === 'attention' ? 'Stopped here' : state === 'waiting' ? 'Waiting' : 'Not run')}>
              {state === 'done' ? <Check size={13} strokeWidth={2.5} /> : state === 'running' ? <LoaderCircle size={14} className="chat-spin" /> : state === 'attention' ? <TriangleAlert size={13} /> : state === 'skipped' ? <Minus size={13} /> : null}
            </span>
            {hasQueries || hasConcepts
              ? <button type="button" className="chat-step-title" aria-expanded={listOpen} onClick={() => (hasQueries ? setQueriesOpen(!queriesOpen) : setConceptsOpen(!conceptsOpen))}><span className={state === 'running' ? 'shimmer-text' : undefined}>{title(key, state, group)}</span>{listOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}</button>
              : <span className={`chat-step-title${state === 'running' ? ' shimmer-text' : ''}`}>{title(key, state, group)}</span>}
            {agents[key]?.model && state !== 'skipped' && <span className={`agent-chip${state === 'running' ? ' is-running' : ''}`} title={t('Model that runs this step')}>
              <ConnectionIcon id={agents[key].connection} />{[t(agents[key].role), modelText(agents[key].model, agents[key].effort)].filter(Boolean).join(' · ')}
            </span>}
            {text && <small>{text}</small>}
            <time>{seconds === null ? '' : durationText(seconds)}</time>
          </div>
          {note && (!hasConcepts || conceptsOpen) && <div className="chat-step-note">{note}</div>}
          {hasConcepts && conceptsOpen && <div className="query-box">
            {plan?.concepts.map(c => <div key={c.label} className="query-row">
              <span className="query-text">{c.synonyms.length ? `${c.label} · ${c.synonyms.join(', ')}` : c.label}</span>
              <span className="query-meta"><span className="query-result">{t(c.role.replace('_', ' '))}</span></span>
            </div>)}
          </div>}
          {hasQueries && queriesOpen && <div className="query-box">
            {searches.map(s => {
              const ok = s.status === 'completed' || s.status === 'zero_results'
              const why = rationaleOf(s.provider, s.query_text)
              return <div key={s.id} className={`query-row${ok ? '' : ' is-attention'}`} title={s.query_text}>
                <Search size={14} aria-hidden />
                {why
                  ? <span className="query-stack"><code className="query-text query-code">{s.query_text}</code><small>{why}</small></span>
                  : <code className="query-text query-code">{s.query_text}</code>}
                <span className={`query-meta${ok ? ' is-ok' : ' is-error'}`}>
                  <span className="query-provider"><ConnectionIcon id={s.provider} />{providerName(s.provider)}</span>
                  <span className="query-result">{ok ? t('{count} of {total}', { count: s.result_count, total: s.provider_total === null ? '?' : compact(s.provider_total) }) : t(s.status.replace('_', ' '))}</span>
                </span>
              </div>
            })}
            {runningSearch && active && <div className="query-row is-running">
              <LoaderCircle size={14} className="chat-spin" aria-hidden />
              <span className="query-text shimmer-text">{t('{provider} · searching', { provider: providerName(runningSearch.kind.split(':')[1] ?? '') })}</span>
            </div>}
          </div>}
        </li>
        })}</ol>
      </>}
    </div>

    {failedSearches.length > 0 && run.status !== 'paused' && <p className="chat-say is-muted">{t('Some searches did not complete: {list}. The results of the other searches are used.', { list: failedSearches.join(', ') })}</p>}
    {run.status === 'paused' && <div className="chat-note is-warning">
      <p>{pauseReasonText(run.pause_reason)}</p>
      {unknownSteps.length > 0 && <p>{t('Unfinished: {steps}. Resuming repeats it; a repeated model call counts against your account usage.', { steps: unknownSteps.map(s => stepLabel(s.kind, s.operation_key)).join(', ') })}</p>}
    </div>}
    {(run.status === 'failed' || run.status === 'cancelled') && run.pause_reason && <div className="chat-note is-warning"><p>{pauseReasonText(run.pause_reason)}</p></div>}
    {run.kind === 'discovery' && run.status === 'completed' && latest && !answer && <p className="chat-say">{t(view.counts.included === 1 ? 'Found {unique} unique works; {included} is included. Check the Sources tab, then generate an answer.' : 'Found {unique} unique works; {included} are included. Check the Sources tab, then generate an answer.', { unique: view.counts.unique, included: view.counts.included })}</p>}
    {children}
    {!children && answer && run.kind === 'answer' && <div className="answer-history-note"><span className="answer-history-icon" aria-hidden="true"><TriangleAlert size={14} /></span><span>{t('An earlier answer: {status}.', { status: t(answer.status.replaceAll('_', ' ')) })}</span></div>}
  </section>
}
