import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, Check, ChevronDown, ChevronRight, Hand, ListPlus, LoaderCircle, Minus, RotateCw, Search, Sparkles, TriangleAlert, Waypoints } from 'lucide-react'
import { api, type ResearchView, type Run, type Verdict, type ReviewCard, type ReviewTargetKind, type SearchRun } from './api'
import { ocrLanguagesText as ocrLanguages } from './ocr'
import { connectionName, failedSectionReasonText, fetchReasonText, pauseDetailText, pauseReasonText, providerName, runStatusLabels, searchQueryTriesLeft, stepLabel, verdictLabels } from './labels'
import { ConnectionIcon } from './connectionIcons'
import { ProtocolApproval } from './ProtocolApproval'
import { ArmReport, NotFoundReport, SignalReport } from './ProbeTables'
import { ModelName } from './ModelName'
import type { ModelText } from './modelText'
import { t, uiLocale } from './i18n'
import { scrollBehavior } from './motion'
import { Button } from '@/components/ui/button'

// The research as a record of work: one node per run on a thin rail, each run one line per phase, details a disclosure deeper.
// The page's event stream refreshes the view; a one-second clock keeps running durations moving between events.
// Pause, resume and cancel sit next to the tabs, so one set of controls serves every tab.

type PhaseKey = 'plan' | 'search' | 'screen' | 'pdf' | 'ocr' | 'semantic' | 'answer' | 'review' | 'sections' | 'assembly'
type PhaseState = 'done' | 'running' | 'attention' | 'waiting' | 'skipped'
type Step = NonNullable<Run['steps']>[number]

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
// Title while running, once done, and before the phase starts or when it is not run.
const titles: Record<PhaseKey, [string, string, string]> = {
  plan: ['Planning the searches', 'Planned the searches', 'Search plan'],
  search: ['Searching the providers', 'Searched the providers', 'Provider searches'],
  screen: ['Screening the candidates', 'Screened the candidates', 'Screening'],
  pdf: ['Downloading open-access PDFs', 'Downloaded open-access PDFs', 'Open-access PDFs'],
  ocr: ['Reading scanned pages with OCR', 'Read scanned pages with OCR', 'OCR of scanned pages'],
  semantic: ['Preparing semantic search', 'Prepared semantic search', 'Semantic search'],
  answer: ['Writing the answer', 'Wrote the answer', 'Source-linked answer'],
  review: ['Reviewing the claims', 'Reviewed the claims', 'Claim review'],
  sections: ['Writing sections', 'Wrote the sections', 'Report sections'],
  assembly: ['Checking the assembled report', 'Checked the assembled report', 'Assembled report'],
}
// Attached PDFs are already on this computer: the same phase reads them rather than downloading anything.
const attachedTitles = (n: number): [string, string, string] => n === 1
  ? ['Reading the attached PDF', 'Read the attached PDF', 'Attached PDF']
  : ['Reading the attached PDFs', 'Read the attached PDFs', 'Attached PDFs']
const discoveryHeadings: Record<string, string> = { active: 'Searching and screening', completed: 'Ran search & screening', paused: 'Search & screening paused', failed: 'Search & screening failed', cancelled: 'Search & screening cancelled' }
const collectionHeadings: Record<string, string> = { active: 'Collecting open-access PDFs', completed: 'Collected open-access PDFs', paused: 'PDF collection paused', failed: 'PDF collection failed', cancelled: 'PDF collection cancelled' }
const fulltextHeadings: Record<string, string> = { active: 'Retrieving the full texts', completed: 'Retrieved the full texts', paused: 'Full-text retrieval paused', failed: 'Full-text retrieval failed', cancelled: 'Full-text retrieval cancelled' }
const readingHeadings: Record<string, string> = { active: 'Reading the full texts', completed: 'Read the full texts', paused: 'Full-text reading paused', failed: 'Full-text reading failed', cancelled: 'Full-text reading cancelled' }
const ocrHeadings: Record<string, string> = { active: 'Reading a PDF with OCR', completed: 'Read a PDF with OCR', paused: 'OCR reading paused', failed: 'OCR reading failed', cancelled: 'OCR reading cancelled' }
const answerHeadings: Record<string, string> = { active: 'Generating the answer', completed: 'Ran answer generation', paused: 'Answer generation paused', failed: 'Answer generation failed', cancelled: 'Answer generation cancelled' }
const reportHeadings: Record<string, string> = { active: 'Writing the report', completed: 'Wrote the report', paused: 'Report paused', failed: 'Report failed', cancelled: 'Report cancelled' }
// The run's stage names the phase it has reached before that phase records its first step.
const stagePhases: Record<string, PhaseKey> = { screening: 'screen', inspection: 'pdf', answer: 'answer', claim_check: 'review' }
const basisLabels: Record<string, string> = { metadata_only: 'metadata only', title_only: 'title only', title_and_abstract: 'title and abstract' }

function phaseOf(kind: string): PhaseKey | null {
  if (kind === 'model:owner_review') return 'review'
  if (kind === 'model:report_plan') return 'plan'
  if (kind === 'model:report_section' || kind === 'model:report_phrase_repair') return 'sections'
  if (kind === 'model:report_review') return 'assembly'
  if (kind === 'model:search_plan') return 'plan'
  // An sw run plans its search in code and asks the user before it searches; those steps are its plan phase, so the
  // phase does not read "waiting" while the run has counted its terms and is waiting for the user.
  if (['code:vocabulary', 'model:vocabulary_labels', 'model:criterion_proposal', 'code:criterion', 'code:protocol_approval',
       'code:term_suggestions', 'model:term_suggestions'].includes(kind)) return 'plan'
  if (kind.startsWith('provider_search')) return 'search'
  if (kind === 'model:screening') return 'screen'
  // An sw run screens abstracts in two steps: code classifies every record, then the model proposes.
  if (kind === 'code:abstract_stage' || kind === 'model:abstract_screening') return 'screen'
  // Citation chaining follows the abstract stage and reads its new works the same way, so it is part of screening (D95).
  if (kind.startsWith('code:chain_') || kind.startsWith('provider_chain:')) return 'screen'
  if (kind === 'fetch_pdf' || kind === 'pdf_other_copy') return 'pdf'
  // An answer run reads equations out of its PDFs before it answers; the PDF phase shows that work under its own title.
  if (kind === 'read_equations') return 'pdf'
  // A full-text retrieval run plans, fetches and totals in code; all three belong to the run's one PDF phase.
  if (kind.startsWith('code:fulltext_') || kind === 'code:fetch_baseline') return 'pdf'
  if (kind === 'code:adjudication_plan' || kind === 'model:fulltext_adjudication' || kind === 'code:adjudication_summary') return 'pdf'
  if (kind.startsWith('ocr_')) return 'ocr'
  if (kind.startsWith('embedding:')) return 'semantic'
  // The answer run compiles its criterion phrases in code just before it chooses passages; that is its answer phase.
  if (kind === 'model:grounded_answer' || kind === 'code:criterion_phrases') return 'answer'
  if (kind === 'model:answer_review') return 'review'
  return null
}

const durationText = (seconds: number) => (seconds < 60 ? t('{s} s', { s: seconds }) : t('{m} min {s} s', { m: Math.floor(seconds / 60), s: seconds % 60 }))
// When the run started: the clock alone for today, with the day for anything older, so the wait between runs is visible.
function startedText(iso: string) {
  const at = new Date(iso)
  const time = at.toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })
  return at.toDateString() === new Date().toDateString() ? t('today {time}', { time }) : `${at.toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short' })} ${time}`
}
const secondsBetween = (from: string, to: number) => Math.max(0, Math.round((to - Date.parse(from)) / 1000))
const present = (values: (string | null)[]) => values.filter((v): v is string => Boolean(v)).sort()
const stepSeconds = (s?: Step) => (s?.started_at && s.finished_at ? secondsBetween(s.started_at, Date.parse(s.finished_at)) : null)
// An embedding model is stored bare for Gemini and as "connection:model" for the others. The built-in model (slice 21)
// is named for where it runs, not by its file name.
const EMBEDDING_CONNECTIONS = new Set(['builtin', 'openai', 'ollama', 'lm_studio'])
const embeddingOf = (stored: string) => {
  const [head, ...rest] = stored.split(':')
  if (head === 'builtin') return { connection: 'builtin', model: rest[0].split('@')[0] }
  return EMBEDDING_CONNECTIONS.has(head) ? { connection: head, model: rest.join(':') } : { connection: 'gemini', model: stored }
}
// A 429 the embedding step waited out stays visible (slice 21).
const waitedText = (output: Step['output']) => output?.rate_limited_waits ? t('rate limited, waited {s} s', { s: Math.round(output.waited_seconds ?? 0) }) : ''
const embeddingServices: Record<string, string> = { gemini: 'Google', openai: 'OpenAI' }
const troubled = (s: Step) => s.status === 'failed' || s.status === 'outcome_unknown'
const plural = (n: number, one: string, many: string, vars: Record<string, string | number> = {}) => t(n === 1 ? one : many, { n, ...vars })
const compact = (n: number) => new Intl.NumberFormat(uiLocale(), { notation: 'compact', maximumFractionDigits: 1 }).format(n)
const tally = (values: string[]) => { const counts = new Map<string, number>(); values.forEach(v => counts.set(v, (counts.get(v) ?? 0) + 1)); return [...counts] }
export function Transcript({ view, emptyText, latestAnswer, modelText, onRetryFailedSearches, onProtocolApproved, onGiveKeyTerms, onChooseCodeQuery, queueCount = 0, onOpenQueue }: {
  view: ResearchView; emptyText: string; latestAnswer: ReactNode; modelText: ModelText
  onRetryFailedSearches?: (run: Run) => Promise<void>
  // The approval card sends its own correction; this only refreshes the view once the backend has taken it.
  onProtocolApproved?: () => void | Promise<void>
  // The way out of a `key_terms_needed` stop: the revision form below, on its key-terms field.
  onGiveKeyTerms?: () => void
  // The way on after the model could not write the query: search with the code's query alone (D92).
  onChooseCodeQuery?: (run: Run) => Promise<void>
  // An sw research's works awaiting a person, named once under the latest reading run (slice 17).
  queueCount?: number; onOpenQueue?: () => void
}) {
  const runs = [...view.runs].reverse()  // the view lists the newest run first
  const lastReading = runs.filter(r => r.kind === 'fulltext_adjudication').at(-1)?.id
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
  // The current question opens the timeline as the user's turn.
  return <>
  <div className="chat-question"><p dir="auto">{view.scope.question}</p></div>
  <div className={`chat${runs.length ? '' : ' is-empty'}`}>
    {runs.map((run, i) => <RunTurn key={run.id} run={run} view={view} now={now} latest={i === runs.length - 1} modelText={modelText} onRetryFailedSearches={onRetryFailedSearches} onProtocolApproved={onProtocolApproved} onGiveKeyTerms={onGiveKeyTerms} onChooseCodeQuery={onChooseCodeQuery}
      queueLine={run.id === lastReading && queueCount > 0 && onOpenQueue ? { count: queueCount, open: onOpenQueue } : null}>
      {view.answers[0]?.run_id === run.id ? latestAnswer : null}
    </RunTurn>)}
    {!runs.length && <div className="chat-say"><Sparkles size={18} strokeWidth={1.6} aria-hidden /><p>{emptyText}</p></div>}
    <div ref={end} className="chat-end" />
    {active && !atEnd && <button type="button" className="chat-jump" onClick={() => end.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'end' })}><ArrowDown size={15} aria-hidden />{t('Jump to latest')}</button>}
  </div>
  </>
}

function RunTurn({ run, view, now, latest, modelText, onRetryFailedSearches, onProtocolApproved, onGiveKeyTerms, onChooseCodeQuery, queueLine = null, children }: {
  run: Run; view: ResearchView; now: number; latest: boolean; modelText: ModelText
  onRetryFailedSearches?: (run: Run) => Promise<void>
  onProtocolApproved?: () => void | Promise<void>; onGiveKeyTerms?: () => void
  onChooseCodeQuery?: (run: Run) => Promise<void>; queueLine?: { count: number; open: () => void } | null; children: ReactNode
}) {
  const active = ACTIVE.has(run.status)
  const [open, setOpen] = useState<boolean | null>(null)
  // Each phase reads as one line; what it found (plan text, concepts, queries, counts) opens under it on request.
  const [openPhases, setOpenPhases] = useState<Partial<Record<PhaseKey, boolean>>>({})
  // While the run works, the phases it has not reached collapse into one "Next:" line; the full ladder stays one click away.
  const [allSteps, setAllSteps] = useState(false)
  const [usageOpen, setUsageOpen] = useState(false)
  const [ownerReview, setOwnerReview] = useState<{ card: ReviewCard; kind: ReviewTargetKind } | null>(null)
  const reviewLookup = useRef<{
    identity: string
    targets: Map<string, Promise<ReviewCard[]>>
    found?: { card: ReviewCard; kind: ReviewTargetKind; status: Run['status'] }
    refresh?: { status: Run['status']; promise: Promise<void> }
  } | null>(null)
  const reviewTargets = JSON.stringify([...view.answers.map(a => ['answer', a.id]), ...view.reportRuns.map(r => ['report', r.id])])
  const candidateReviewPlan = Boolean(run.target?.plan?.groups.some(g => g.source_ids !== undefined))
  const reviewTargetKind = run.target?.target_kind
  const reviewTargetId = run.target?.target_id
  useEffect(() => {
    if (run.kind !== 'review') return
    let live = true
    const identity = `${view.research.id}:${run.id}`
    if (reviewLookup.current?.identity !== identity) reviewLookup.current = { identity, targets: new Map() }
    const lookup = reviewLookup.current
    const storedTarget = reviewTargetKind && reviewTargetId
    const targets = storedTarget ? [[reviewTargetKind, reviewTargetId] as [ReviewTargetKind, string]] : JSON.parse(reviewTargets) as [ReviewTargetKind, string][]
    void (async () => {
      // Source-group plans alone do not identify a target; confirm it against the exact version review list.
      if (!storedTarget && candidateReviewPlan && !lookup.found) {
        const candidates = await api.candidates(view.research.id)
        for (const candidate of candidates) {
          const card = await api.candidate(view.research.id, candidate.id)
          targets.push(...card.versions.map(v => ['candidate', v.id] as [ReviewTargetKind, string]))
        }
      }
      for (const [kind, id] of targets) {
        if (lookup.found || !live) break
        const key = `${kind}:${id}`
        // Keep even pending/failed lookups: research events must not repeat a full-card list request.
        let request = lookup.targets.get(key)
        if (!request) { request = api.reviews(view.research.id, kind, id); lookup.targets.set(key, request) }
        const cards = await request.catch(() => [])
        const card = cards.find(c => c.run_id === run.id)
        if (card) lookup.found = { card, kind, status: run.status }
      }
      const found = lookup.found
      if (!found || !live) return
      if (found.status !== run.status) {
        if (lookup.refresh?.status !== run.status) {
          const refresh = { status: run.status, promise: Promise.resolve() }
          lookup.refresh = refresh
          refresh.promise = api.review(view.research.id, found.card.id).then(detail => {
            if (lookup.refresh !== refresh) return
            found.card = { ...found.card, state: detail.state, failure_reason: detail.failure_reason, pause_reason: detail.pause_reason, outcome_unknown: detail.outcome_unknown }
            found.status = refresh.status
          })
        }
        await lookup.refresh.promise
      }
      if (live) setOwnerReview({ card: found.card, kind: found.kind })
    })().catch(() => { /* Keep the last recorded assessment if its status refresh fails. */ })
    return () => { live = false }
  }, [run.id, run.kind, run.status, view.research.id, reviewTargets, candidateReviewPlan, reviewTargetKind, reviewTargetId])
  // A finished run folds away once something follows it; the latest search stays open so its queries can be read.
  const expanded = open ?? (run.status !== 'completed' || (latest && run.kind === 'discovery'))
  const clock = active ? Math.max(now, Date.parse(run.updated_at)) : Date.parse(run.updated_at)

  const steps = run.steps ?? []
  // An sw discovery run queued since slice 17a fetches the full text itself, beside its screening.
  const overlap = run.kind === 'discovery' && (run.budget.fulltext_fetch as unknown as { mode?: string } | undefined)?.mode === 'overlap'
  const order: PhaseKey[] = run.kind === 'review' ? ['review'] : run.kind === 'report' ? ['plan', 'sections', 'assembly'] : run.kind === 'discovery' ? ['plan', 'search', 'screen', ...(overlap ? ['pdf' as const] : [])] : run.kind === 'pdf_collection' || run.kind === 'fulltext_fetch' || run.kind === 'fulltext_adjudication' ? ['pdf'] : run.kind === 'pdf_ocr' ? ['ocr'] : ['pdf', 'semantic', 'answer', ...(view.reviewer.model ? ['review' as const] : [])]
  const groups = order.map(key => steps.filter(s => phaseOf(s.kind) === key))
  // When a model's advice on the warned terms was applied and the run went on without asking (D232), one plain line per
  // advised term says what the model did and why. Nothing warned, nothing advised: no line.
  const advised = (run.approval?.advice_applied ?? []).filter(row => row.recommendation !== null)
  const adviceModel = run.approval?.advice_model
  const adviceLines = advised.length > 0 && <ul className="chat-advice-lines">{advised.map(row => <li key={row.phrase}>
    {adviceModel && <><ModelName connection={adviceModel.connection} text={modelText(adviceModel.model)} />{' '}</>}
    <span dir="auto">{row.applied
      ? t('removed “{phrase}” from the search ({from} → {to} papers):', { phrase: row.phrase, from: row.matches.toLocaleString(uiLocale()), to: row.matches_without_term.toLocaleString(uiLocale()) })
      : row.not_applied ? t('advised removing “{phrase}”, but it is the last word of its group, so it stayed:', { phrase: row.phrase })
      : t('kept “{phrase}”:', { phrase: row.phrase })} {row.reason}</span>
  </li>)}</ul>
  const reached = run.kind === 'report' && !active ? 2 : Math.max(order.indexOf(stagePhases[run.stage]), ...groups.map((group, i) => (group.length ? i : -1)))
  // A citation chain's requests are not searches of the question; the screening phase reports them (D95).
  const searches = view.search_runs.filter(s => s.run_id === run.id && !s.query_text.startsWith('chain:'))
  const answer = view.answers.find(a => a.run_id === run.id)
  const started = present(steps.map(s => s.started_at))[0] ?? run.created_at
  const unknownSteps = steps.filter(s => s.status === 'outcome_unknown')
  const failedOcrPages = steps.filter(s => s.kind === 'ocr_page' && troubled(s)).map(s => s.operation_key.split(':')[2])
  // A failed search no longer stops the run (D18); name the provider that is missing so the results are not read as
  // complete. Why it failed stays on its query row in the phase details, where the other provider results are.
  const failedProviders = [...new Map(steps.filter(s => s.kind.startsWith('provider_search') && troubled(s))
    .map(s => [s.kind.split(':')[1] ?? '', providerName(s.kind.split(':')[1] ?? '')])).entries()]
  const retrying = run.kind === 'discovery' && !active && (run.status === 'completed' || run.status === 'paused')
    && steps.some(s => s.kind.startsWith('provider_search') && troubled(s))
  const runningSearch = groups[order.indexOf('search')]?.find(s => s.status === 'running')
  const plan = run.plan
  // The screening the run itself proposed on, and the sources the answer run reads.
  const screened = view.sources.filter(s => s.found_in_revision === run.scope_revision)
  const included = view.sources.filter(s => s.selection.state === 'included')
  // The similarity step belongs to no phase of its own; the screening phase reports it.
  const similarity = steps.find(s => s.kind.startsWith('similarity:'))
  // What the citation chain did in this run, once its summary is written (D95).
  const chain = steps.find(s => s.kind === 'code:chain_summary' && s.status === 'succeeded')
  // A pdf_ocr run (D51): its PDF, the pages without text it found, and what became of the merged text.
  const ocrSource = run.kind === 'pdf_ocr' ? view.sources.find(s => s.source_version_id === run.target?.source_version_id) : undefined
  const ocrAsset = ocrSource?.access.assets.find(a => a.id === run.target?.asset_id)
  const ocrPages = steps.find(s => s.kind === 'ocr_pages')?.output?.image_pages
  const rationaleOf = (provider: string, query: string) => plan?.queries.find(q => q.provider_id === provider && q.query_text === query)?.rationale ?? ''

  // With the fetch beside it, screening is over only once its final retrieval plan is written; both phases can run at once.
  const fetchPlanned = steps.some(s => s.kind === 'code:fulltext_plan' && s.status === 'succeeded')
  const fetchSummary = steps.find(s => s.kind === 'code:fulltext_summary' && s.status === 'succeeded')?.output
  const fetchWorks = steps.filter(s => s.kind === 'code:fulltext_work')
  const stateOf = (i: number): PhaseState => {
    if (run.kind === 'review' && ownerReview && ['partial', 'failed', 'cancelled', 'paused'].includes(ownerReview.card.state)) return 'attention'
    if (run.kind === 'report' && order[i] === 'assembly') return active ? 'waiting' : run.status === 'completed' ? 'done' : 'attention'
    if (run.kind === 'report' && order[i] === 'sections' && run.status === 'paused') return 'attention'
    const hasTrouble = groups[i].some(troubled)
    if (groups[i].some(step => step.status === 'running')) return 'running'
    if (overlap && active && order[i] === 'screen' && groups[i].length && !fetchPlanned) return 'running'
    if (i < reached) return hasTrouble ? 'attention' : groups[i].length ? 'done' : 'skipped'
    if (i === reached) return active ? 'running' : hasTrouble ? 'attention' : run.status === 'completed' ? 'done' : 'attention'
    if (active && reached < 0 && i === 0 && run.status !== 'queued') return 'running'
    return active || run.status === 'paused' ? 'waiting' : 'skipped'
  }

  // A research of attached files alone reads PDFs it already has; nothing is downloaded, so the PDF phase says so.
  const attachedOnly = view.scope.source_scope === 'attached'

  // One outcome per source: a copy found after its link refused counts as downloaded, not as a failure. Equation and
  // reading steps are other work in the same phase and never count as a download.
  const pdfOutcomes = (group: Step[]) => {
    const outcomes = new Map<string, Step>()
    group.filter(s => s.kind === 'fetch_pdf' || s.kind === 'pdf_other_copy').forEach(s => { const svid = s.operation_key.split(':')[1]; if (outcomes.get(svid)?.status !== 'succeeded') outcomes.set(svid, s) })
    // A work step succeeds even when no full text was found, so only a work with a stored file counts; elsewhere one success per source.
    const works = group.filter(s => s.kind === 'code:fulltext_work')
    const ok = works.length ? works.filter(s => s.status === 'succeeded' && s.output?.asset_id) : [...outcomes.values()].filter(s => s.status === 'succeeded')
    return { outcomes, works, ok }
  }
  // The full-text reading counts works, not model calls: each work is read twice, under keys naming the work and the pass.
  const readingWorks = (group: Step[]) => {
    const passes = new Map<string, Step[]>()
    group.filter(s => s.kind === 'model:fulltext_adjudication').forEach(s => {
      const work = s.operation_key.replace(/^fulltext_adjudication:/, '').replace(/:[^:]*$/, '')
      passes.set(work, [...(passes.get(work) ?? []), s])
    })
    const settled = [...passes.values()].filter(steps => steps.filter(s => s.status === 'succeeded' || troubled(s)).length >= 2).length
    const planned = group.find(s => s.kind === 'code:adjudication_plan')?.output?.works?.length ?? 0
    return { done: settled, total: Math.max(planned, passes.size) }
  }
  const equationPdfs = (group: Step[]) => new Set(group.filter(s => s.kind === 'read_equations').map(s => s.operation_key)).size

  const title = (key: PhaseKey, state: PhaseState, group: Step[]) => {
    if (run.kind === 'review') return t('Review by another model')
    if (run.kind === 'report' && key === 'plan') return t(state === 'running' ? 'Planning the report' : state === 'done' ? 'Planned the report' : 'Report plan')
    const finished = searches.filter(s => s.status === 'completed' || s.status === 'zero_results').length
    if ((state === 'done' || state === 'attention') && key === 'search' && finished) return plural(finished, 'Conducted {n} search', 'Conducted {n} searches')
    // The fetch inside a discovery run counts works, not files: N of the M works it has claimed so far are settled.
    // The works are claimed as screening goes on, so a total would keep growing: the line says how many were checked so far.
    if (overlap && key === 'pdf' && state === 'running' && fetchWorks.length) return plural(fetchWorks.filter(s => s.status === 'succeeded' || s.status === 'failed').length, 'Checked {n} work for full text so far', 'Checked {n} works for full text so far')
    if (overlap && key === 'pdf' && state === 'done' && fetchSummary) return plural(fetchSummary.fetched ?? 0, 'Retrieved the full text of {n} work', 'Retrieved the full text of {n} works')
    if (key === 'pdf' && group.some(s => s.kind === 'model:fulltext_adjudication' || s.kind === 'code:adjudication_plan')) {
      const { done, total } = readingWorks(group)
      if (state === 'running') return t('Reading the full texts: {done} of {total} works', { done, total })
      if (state === 'done') return plural(done, 'Read the full text of {n} work', 'Read the full text of {n} works')
      return t('Full-text reading')
    }
    // Equations are read from PDFs already held, after any download of the phase has finished.
    const equations = equationPdfs(group)
    const downloading = group.some(s => s.kind === 'fetch_pdf' || s.kind === 'pdf_other_copy')
    const readingEquations = group.some(s => s.kind === 'read_equations' && s.status === 'running')
    if (key === 'pdf' && equations && (!downloading || readingEquations)) {
      // Only finished reads count: the answer can be written while equations of some PDFs are still waiting.
      const read = new Set(group.filter(s => s.kind === 'read_equations' && s.status === 'succeeded').map(s => s.operation_key)).size
      if (state === 'running') return t('Reading equations: {read} of {n} PDFs', { read, n: equations })
      return read === equations ? plural(equations, 'Read equations in {n} PDF', 'Read equations in {n} PDFs') : t('Equations read in {read} of {n} PDFs', { read, n: equations })
    }
    if (state === 'done' && key === 'pdf') return plural(pdfOutcomes(group).ok.length, attachedOnly ? 'Read {n} attached PDF' : 'Downloaded {n} open-access PDF', attachedOnly ? 'Read {n} attached PDFs' : 'Downloaded {n} open-access PDFs')
    if (state === 'done' && key === 'ocr' && ocrPages) return plural(ocrPages.length, 'Read {n} scanned page with OCR', 'Read {n} scanned pages with OCR')
    if (state === 'done' && key === 'review' && answer?.review?.status === 'completed') return plural(answer.review.reviews.length, 'Reviewed {n} claim', 'Reviewed {n} claims')
    const [running, done, idle] = key === 'pdf' && attachedOnly ? attachedTitles(included.length) : titles[key]
    return t(state === 'running' ? running : state === 'done' ? done : idle)
  }

  const detail = (key: PhaseKey, state: PhaseState, group: Step[]): string => {
    const attempt = Math.max(0, ...group.map(s => s.attempt))
    const attemptText = attempt > 1 && state === 'running' ? t('attempt {n}', { n: attempt }) : ''
    if (state === 'waiting') return t('Waiting')
    if (state === 'skipped') return t(key === 'pdf' && run.status === 'completed' ? (attachedOnly ? 'No attached PDF to read' : 'No open-access PDF to download') : key === 'semantic' && run.status === 'completed' ? 'Not used' : run.status === 'completed' ? 'Not needed' : 'Not run')
    switch (key) {
      case 'plan': {
        if (state !== 'done' || !plan) return attemptText
        const synonyms = plan.concepts.reduce((sum, c) => sum + c.synonyms.length, 0)
        return [plural(plan.concepts.length, '{n} concept', '{n} concepts'), plural(synonyms, '{n} synonym', '{n} synonyms')].join(' · ')
      }
      case 'search': {
        if (!searches.length) return ''
        // The line keeps the totals only; the per-provider figures are in the phase details, on the query rows.
        const found = searches.reduce((sum, s) => sum + (s.status === 'completed' ? s.result_count : 0), 0)
        // Unique works are counted per question revision, not per run, so the line keeps only what this run's searches returned.
        return plural(found, '{n} record', '{n} records')
      }
      case 'screen': {
        if (state === 'running') {
          // Abstracts the model has read: each batch is read twice, so a work counts once however many reads of it are done.
          const read = new Set(group.flatMap(s => s.kind === 'model:abstract_screening' && s.status === 'succeeded' ? s.output?.candidate_ids ?? [] : [])).size
          const stages = group.filter(s => (s.kind === 'code:abstract_stage' || s.kind === 'code:chain_abstract_stage') && s.output?.batch_sizes)
          const chainRead = group.some(s => s.operation_key.startsWith('abstract_screening:chain:'))
          const total = stages.reduce((sum, s) => sum + (s.output?.batch_sizes ?? []).reduce((a, b) => a + b, 0), 0)
          // Without the code's list of what it queued (an older run) or with a chain stage not listed yet, no total is claimed.
          if (!stages.length || (chainRead && !stages.some(s => s.kind === 'code:chain_abstract_stage'))) return read ? plural(read, '{n} abstract read', '{n} abstracts read') : ''
          return t('{read} of {total} abstracts read', { read, total })
        }
        return t('{included} included · {excluded} excluded · {pending} undecided', { included: view.counts.included, excluded: view.counts.excluded, pending: view.counts.pending })
      }
      case 'pdf': {
        // One outcome per source: a copy found after its link refused counts as downloaded, not as a failure.
        if (group.some(s => s.kind === 'model:fulltext_adjudication' || s.kind === 'code:adjudication_plan')) return attemptText
        const { outcomes, works, ok } = pdfOutcomes(group)
        const reasons = tally([...outcomes.values()].filter(troubled).map(s => fetchReasonText(s.error_code, (s.error as { http_status?: number } | null)?.http_status)))
        const failed = reasons.reduce((sum, [, n]) => sum + n, 0)
        const pages = ok.reduce((sum, s) => sum + (s.output?.page_count ?? 0), 0)
        const parts = [works.length ? plural(ok.length, '{n} full text found', '{n} full texts found') : state === 'running' && group.length ? plural(ok.length, attachedOnly ? '{n} read' : '{n} downloaded', attachedOnly ? '{n} read' : '{n} downloaded') : '',
          state === 'done' && pages ? t('{pages} pages · {passages} passages', { pages, passages: ok.reduce((sum, s) => sum + (s.output?.passage_count ?? 0), 0) }) : '',
          failed ? t('{n} not downloaded ({reasons})', { n: failed, reasons: reasons.map(([reason, n]) => `${n} ${reason}`).join(', ') }) : '']
        return parts.filter(Boolean).join(' · ')
      }
      case 'ocr': {
        const read = group.filter(s => s.kind === 'ocr_page' && s.status === 'succeeded').length
        const failed = group.filter(s => s.kind === 'ocr_page' && troubled(s)).length
        const merged = group.find(s => s.kind === 'ocr_merge' && s.status === 'succeeded')?.output
        const last = ocrAsset?.ocr?.last_read
        return [ocrSource?.title ?? '', ocrPages && state !== 'done' ? t('{done} of {total} pages read', { done: read, total: ocrPages.length }) : '',
          failed ? plural(failed, '{n} page not read', '{n} pages not read') : '',
          merged && last ? plural(last.pages_with_text, '{n} page with text', '{n} pages with text') : '',
          merged && last?.blank_pages ? plural(last.blank_pages, '{n} blank page skipped', '{n} blank pages skipped') : '',
          merged ? (merged.outcome === 'current' ? t('in use') : t('not used: {reason}', { reason: merged.rejection_reason ?? '' })) : '',
          run.target?.languages ? ocrLanguages(run.target.languages) : ''].filter(Boolean).join(' · ')
      }
      case 'semantic': {
        if (state === 'running') return attemptText
        const step = group.find(s => s.status === 'succeeded' || s.status === 'partial') ?? group[group.length - 1]
        const builtin = step?.kind.startsWith('embedding:builtin:')
        const output = step?.output
        const service = output ? embeddingServices[output.provider ?? embeddingOf(output.model ?? '').connection] : undefined
        // Shown on every finished step, failed or partial too: which uploaded text went out, and which may have.
        // Issued with no vectors back, or cut off before its reply (whether the request even started is then not known).
        const unconfirmed = (output?.uploaded_passages_attempted ?? 0) - (output?.uploaded_passages_confirmed ?? 0)
        const uploads = service ? [
          output?.uploaded_files_confirmed ? plural(output.uploaded_files_confirmed, 'Text of {n} uploaded PDF was sent to {service}', 'Text of {n} uploaded PDFs was sent to {service}', { service }) : '',
          unconfirmed ? plural(unconfirmed, '{n} uploaded passage went in a request that brought no vectors back; whether {service} received it is not known', '{n} uploaded passages went in a request that brought no vectors back; whether {service} received them is not known', { service }) : '',
          output?.uploaded_passages_unknown ? plural(output.uploaded_passages_unknown, '{n} uploaded passage was being sent when the step stopped; whether {service} received it is not known', '{n} uploaded passages were being sent when the step stopped; whether {service} received them is not known', { service }) : '',
        ] : []
        if (state === 'attention') return [t(output?.stored_other_dimension ? 'Stored vectors differ in size from the question’s · continued with keyword search' : builtin ? 'The built-in model was not available · continued with keyword search' : 'Unavailable · continued with keyword search'), waitedText(output ?? null), ...uploads].filter(Boolean).join(' · ')
        if (output?.skipped) return t(output.reason === 'column_not_english' ? 'Not used: the column is not in English' : 'Not used: no English sentence for the built-in model')
        if (output?.passages === undefined || output.embedded === undefined) return ''
        return [step?.status === 'partial'
          ? t('{n} of {m} passages ranked by meaning · the rest by keyword search', { n: (output.from_store ?? 0) + output.embedded, m: output.passages })
          : t('{passages} passages ranked by meaning', { passages: output.passages }),
        waitedText(output),
        ...uploads,
        ].filter(Boolean).join(' · ')
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
    if (run.kind === 'review' && key === 'review') return <ul className="chat-list">{(run.target?.plan?.groups ?? []).map(item => {
      const step = group.find(s => s.operation_key === `owner_review:${item.group_index}`)
      const status = step?.status === 'succeeded' ? 'done' : step && troubled(step) ? 'attention' : step?.status === 'running' ? 'running' : 'waiting'
      return <li key={item.group_index} className={`is-${status}`}><span className="chat-step-icon" role="img" aria-label={t(status === 'done' ? 'Done' : status === 'attention' ? 'Stopped here' : status === 'running' ? 'In progress' : 'Waiting')}>{status === 'done' ? <Check size={13} aria-hidden /> : status === 'attention' ? <TriangleAlert size={13} aria-hidden /> : status === 'running' ? <LoaderCircle size={14} aria-hidden /> : <Minus size={13} aria-hidden />}</span><span>{t('Group {i} of {n}', { i: item.group_index, n: item.group_count })}{step?.error_code && <small>{pauseReasonText(step.error_code)}</small>}{step?.status === 'outcome_unknown' && <small>{t('Outcome unknown')}</small>}</span></li>
    })}</ul>
    if (run.kind === 'report' && key === 'assembly' && group.some(step => step.kind === 'model:report_review')) return <p>{t('Report review')}</p>
    if (run.kind === 'report' && key === 'sections' && group.length) return <>{group.filter(step => step.kind === 'model:report_section').map(step => {
      const section = step.operation_key.replace('report_section:', '')
      const needsRewrite = run.pause_reason === 'section_must_be_rewritten' &&
        Array.isArray((run.error as { sections?: string[] } | null)?.sections) &&
        (run.error as { sections: string[] }).sections.includes(section)
      const reasons = (run.error as { reasons?: { section_id?: string; code?: string }[] } | null)?.reasons
      const code = Array.isArray(reasons) ? reasons.find(reason => reason?.section_id === section)?.code : undefined
      const reason = typeof code === 'string' && code ? failedSectionReasonText(code) : ''
      const outcome = needsRewrite ? reason ? t('{section}: must be written again: {reason}', { section, reason }) : t('{section}: must be written again', { section }) : step.status === 'succeeded' ? t('{section} written', { section }) : step.status === 'failed' || step.status === 'outcome_unknown' ? reason ? t('{section} failed: {reason}', { section, reason }) : t('{section} failed', { section }) : step.status === 'running' ? t('{section}: being written', { section }) : t('{section}: waiting', { section })
      return <p key={step.id} className="chat-report-line">{outcome}</p>
    })}</>
    // A search phase reports even when a provider failed: the totals of the providers that did answer still hold.
    if (state !== 'done' && !(key === 'search' && state === 'attention')) return null
    switch (key) {
      case 'search': {
        // Per provider: the records taken, and the total the provider reported when it is larger than what was taken.
        const perProvider = new Map<string, { taken: number; total: number | null }>()
        searches.forEach(s => {
          const seen = perProvider.get(s.provider) ?? { taken: 0, total: null }
          perProvider.set(s.provider, { taken: seen.taken + (s.status === 'completed' ? s.result_count : 0),
            total: s.provider_total === null ? seen.total : (seen.total ?? 0) + s.provider_total })
        })
        // Per round, the works each source brought after the DOI and work merge, and how many no other source did
        // (D93). A run searched before these were kept says so instead of showing zeros.
        const counts = run.source_counts
        // An sw research's rows also carry what each arm found that was later included or confirmed (slice 19).
        const arms = counts?.counted && counts.arms ? <ArmReport counts={counts} probes={view.probes}
          modelTerms={Boolean(run.approval?.approved?.terms.some(term => term.origin === 'model'))} /> : null
        // The person's works no search of this question revision found, under its latest discovery run.
        const notFound = view.probes && view.runs.find(r => r.kind === 'discovery' && r.scope_revision === view.research.current_scope_revision)?.id === run.id
          ? <NotFoundReport probes={view.probes} /> : null
        const perSource = !arms && counts && (counts.counted
          ? counts.rounds.map(round => <p key={round.round} className="chat-provider-totals">
            <span>{t('Round {n}', { n: round.round })}</span>
            {round.sources.map(source => <span key={source.provider_id}>
              <ConnectionIcon id={source.provider_id} />{providerName(source.provider_id)} {t('{works} works, {only} no other source’s search found', { works: source.works, only: source.only })}
            </span>)}</p>)
          : <p className="chat-report-line"><span>{t('Works per source were not counted for this run')}</span></p>)
        // What the citation chain brought, counted the same way, beside the searches rather than as a round of them.
        const chained = !arms && counts?.counted && counts.chain ? <p className="chat-provider-totals">
          <span>{t('Citation chaining')}</span>
          <span><ConnectionIcon id="openalex" />{t('{works} works, {only} not found by any search', { works: counts.chain.works, only: counts.chain.only })}</span>
        </p> : null
        // A single provider is already named on each query row below.
        const totals = perProvider.size < 2 ? null : <p className="chat-provider-totals">{[...perProvider].map(([id, { taken, total }]) => <span key={id}>
          <ConnectionIcon id={id} />{providerName(id)} {total !== null && total > taken ? t('{count} of {total}', { count: taken, total: compact(total) }) : taken}
        </span>)}</p>
        if (!totals && !perSource && !chained && !arms && !notFound) return null
        return <>{totals}{perSource}{chained}{arms}{notFound}</>
      }
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
        const similarityModel = similarity ? embeddingOf(similarity.output?.model ?? similarity.kind.slice('similarity:'.length)) : null
        // What the similarity step gave the ranking (slice 21): scores it made, scores from an earlier run it read,
        // part of the pool when a batch failed, or nothing when the model was not available.
        const simOut = similarity?.output ?? null
        const fromStore = simOut?.from_store ?? 0
        const scoredCount = fromStore + (simOut?.embedded ?? 0)
        const simTotal = simOut?.sources ?? 0
        const builtinSim = similarityModel?.connection === 'builtin'
        const similarityScored = similarity?.status === 'succeeded' || similarity?.status === 'partial' || fromStore > 0
        const similarityText = !similarity ? '' : [
          similarity.status === 'succeeded'
            ? simOut?.embedded === 0 && fromStore > 0
              ? builtinSim && simOut?.model_installed === false  // what the step recorded when it ran, not today's setting
                ? plural(fromStore, '{n} record compared with the question earlier; the built-in model was not installed when this step ran', '{n} records compared with the question earlier; the built-in model was not installed when this step ran')
                : plural(fromStore, '{n} record compared with the question earlier', '{n} records compared with the question earlier')
              : plural(simTotal || (simOut?.sources ?? 0), '{n} record compared with the question', '{n} records compared with the question')
            : scoredCount > 0 ? t('{n} of {m} records compared with the question', { n: scoredCount, m: simTotal })
              : builtinSim ? t('The built-in model was not available; the records were ordered without comparing them with the question')
                : t('Similarity unavailable; ordered by search position'),
          waitedText(simOut),
        ].filter(Boolean).join(' · ')
        const timed = (step?: Step) => { const s = stepSeconds(step); return s === null ? null : <time>{durationText(s)}</time> }
        // One line per finding, each with the time its step took.
        return <>
          {similarity && similarityModel && <p className="chat-report-line">
            <span>{similarityText}
              {similarityScored && <span className="chat-run-model chat-report-model"><ConnectionIcon id={similarityModel.connection} /><span className="sr-only">{connectionName(similarityModel.connection)} · </span>{builtinSim ? t('This computer · built-in') : similarityModel.model}</span>}</span>
            {timed(similarity)}
          </p>}
          {lines.length > 0 && <p className="chat-report-line"><span>{lines.join(' · ')}</span></p>}
          {run.signals && <SignalReport table={run.signals} probes={view.probes} />}
          {chain && <ChainReport steps={steps} view={view} />}
          {run.screening_notes.map(note => <p key={note.step_id} className="chat-report-line"><span>{note.text}</span>{timed(steps.find(s => s.id === note.step_id))}</p>)}
        </>
      }
      case 'pdf': {
        const candidates = included.flatMap(s => s.access.pdf_candidates)
        const verified = candidates.filter(c => c.identity_status === 'doi_verified' || c.identity_status === 'title_verified').length
        const abstractOnly = included.filter(s => !s.access.assets.length && s.access.abstract_passage_id).length
        const lines = [
          candidates.length ? t('PDF candidates: {list}', { list: tally(candidates.map(c => c.provider)).map(([id, n]) => `${providerName(id)} ${n}`).join(' · ') }) : '',
          verified ? plural(verified, '{n} PDF candidate confirmed as the right paper', '{n} PDF candidates confirmed as the right paper') : '',
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
  const { connection: embeddingConnection, model: embeddingModel } = embeddingOf(embeddingStoredModel)
  const embeddingProviders: Record<string, string> = { gemini: 'Gemini', builtin: 'This computer · built-in', openai: 'OpenAI', ollama: 'Ollama', lm_studio: 'LM Studio' }
  const agents: Partial<Record<PhaseKey, { role: string; connection: string; model: string | null; effort: string | null }>> = {
    plan: run.kind === 'report' ? undefined : literature, screen: literature,
    semantic: embeddingStep ? { role: embeddingProviders[embeddingConnection], connection: embeddingConnection, model: embeddingModel, effort: null } : undefined,
    answer: { role: 'Answer', connection: answer?.model?.connection ?? scope.model_connection, model: answer?.model?.resolved_model ?? answer?.model?.requested_model ?? scope.requested_model, effort: scope.reasoning_effort },
    review: run.kind === 'review' ? (ownerReview ? { role: 'Review', connection: ownerReview.card.requested_model.connection, model: ownerReview.card.requested_model.model, effort: ownerReview.card.requested_model.reasoning_effort } : undefined) : { role: 'Reviewer', connection: answer?.review?.model?.connection ?? view.reviewer.connection ?? scope.model_connection, model: answer?.review?.model?.resolved_model ?? view.reviewer.model, effort: view.reviewer.reasoning_effort },
  }
  const providers = new Intl.ListFormat(uiLocale(), { type: 'conjunction' }).format(view.scope.search_providers.map(providerName))
  // Worded as what happened, so it reads apart from the run strip's status next to the tabs.
  const outcome = active ? 'active' : run.status
  const reviewState = ownerReview?.card.state ?? run.status
  const reviewFailure = ownerReview?.card.failure_reason ?? null
  const label = run.kind === 'review' ? [t('Review by another model'), t(reviewState === 'partial' ? 'Partial' : runStatusLabels[reviewState]), ...(reviewState === 'failed' ? [pauseReasonText(reviewFailure) || t('The run failed.')] : [])].join(' · ') : t((run.kind === 'discovery' ? discoveryHeadings : run.kind === 'pdf_collection' ? collectionHeadings : run.kind === 'fulltext_fetch' ? fulltextHeadings : run.kind === 'fulltext_adjudication' ? readingHeadings : run.kind === 'pdf_ocr' ? ocrHeadings : run.kind === 'report' ? reportHeadings : answerHeadings)[outcome] ?? runStatusLabels[run.status])
  const olderRevision = run.scope_revision !== view.research.current_scope_revision
  // What the run asked of the model against what it was allowed; the limit is left out once the count passes it.
  const calls = run.usage.model_calls ?? 0
  const callLimit = run.budget.max_model_calls ?? 0
  const spend = callLimit && calls <= callLimit
    ? t(calls === 1 ? 'The model was asked once (limit {limit})' : 'The model was asked {calls} times (limit {limit})', { calls, limit: callLimit })
    : t(calls === 1 ? 'The model was asked once' : 'The model was asked {calls} times', { calls })
  const callLimitReached = callLimit > 0 && calls >= callLimit
  // Which model ran each model phase of this run, listed once here rather than on every step line.
  const models = order.filter((key, i) => agents[key]?.model && stateOf(i) !== 'skipped').map(key => agents[key]!)
    .filter((agent, i, all) => all.findIndex(a => a.role === agent.role) === i)  // the literature model plans and screens; name it once
    .map(agent => <span key={agent.role} className="chat-run-model">{agent.role && <>{t(agent.role)} · </>}<ModelName connection={agent.connection} text={modelText(agent.model, agent.effort)} /></span>)
  // Live runs read as one line of work: what the run has not reached, and what it skips, stay out until it is done.
  const phaseStates = order.map((_, i) => stateOf(i))
  const idle = (state: PhaseState) => state === 'waiting' || state === 'skipped'
  const collapsed = active && !allSteps && phaseStates.some(idle)
  const waitingNext = collapsed ? order.filter((_, i) => phaseStates[i] === 'waiting').map(key => t((key === 'pdf' && attachedOnly ? attachedTitles(included.length) : titles[key])[2]).toLocaleLowerCase(uiLocale())) : []
  const busyEquationPdfs = new Set(steps.filter(step => step.kind === 'read_equations' && step.output?.outcome === 'file_busy').map(step => step.output?.asset_id)).size
  return <section className={`chat-turn${active ? ' is-active' : ''}`}>
    <div className="chat-group">
      <button type="button" className="chat-toggle" data-run-id={run.id} aria-expanded={expanded} onClick={() => setOpen(!expanded)}>
        {expanded ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
        <span className={active ? 'shimmer-text' : undefined}>{label}{olderRevision ? ` ${t('· for question revision {n}', { n: run.scope_revision })}` : ''}</span>
        {active && <LoaderCircle size={14} className="chat-spin" aria-hidden />}
        <span className="chat-when">{startedText(started)}</span>
        <time>{durationText(secondsBetween(started, clock))}</time>
      </button>
      {expanded && <>
        {run.kind === 'answer' && active && run.stage === 'inspection' && steps.some(step => step.kind === 'read_equations' && step.status === 'running') && !steps.some(step => step.kind === 'equations_skip') && <p className="chat-report-line"><button type="button" className="chat-steps-toggle" onClick={() => { api.skipEquations(run.id).catch(() => undefined) }}>{t('Answer now with PDF text')}</button></p>}
        {steps.filter(step => step.kind === 'equations_skipped' && step.status === 'succeeded').map(step => <p key={step.id} className="chat-report-line">{t('Answered now with PDF text; equations of {skipped} PDFs were not read ({read} were read).', { skipped: step.output?.pdfs_skipped ?? 0, read: step.output?.pdfs_read ?? 0 })}</p>)}
        {busyEquationPdfs > 0 && <p className="chat-report-line">{t(busyEquationPdfs === 1 ? 'PDF busy; equations of {n} PDF were not read in this run.' : 'PDF busy; equations of {n} PDFs were not read in this run.', { n: busyEquationPdfs })}</p>}
        {(run.kind === 'review' || (latest && active && !collapsed)) && <div className="chat-run-plan" role="note">
          <Sparkles size={14} strokeWidth={1.8} aria-hidden />
          <div><p className="chat-run-plan-title">{run.kind === 'review' ? (ownerReview && run.target?.plan?.groups ? plural(run.target.plan.groups.length, 'A model you chose reads a stored copy of the {target} in {n} group. It changes nothing in the {target}.', 'A model you chose reads a stored copy of the {target} in {n} groups. It changes nothing in the {target}.', { target: t(ownerReview.kind === 'candidate' ? 'candidate' : ownerReview.kind === 'answer' ? 'answer' : 'report'), n: run.target.plan.groups.length }) : t('A model you chose reads a stored copy. It changes no target text.')) : run.kind === 'report' ? t('Write a sectioned report from the evidence table, one model step per section.') : run.kind === 'discovery' ? t('Search {providers}, then screen the candidates.', { providers }) : run.kind === 'pdf_collection' ? t('Try each included source’s open PDF links, then look once for another open copy.') : run.kind === 'fulltext_fetch' ? t('Retrieve the open full text of the candidate works in rank order; nothing is included or excluded by this.') : run.kind === 'fulltext_adjudication' ? t('A model reads selected passages of each work twice; code checks every quote on the page and decides.') : run.kind === 'pdf_ocr' ? t('Read the pages without text of “{title}” with Tesseract on this computer, one page at a time. No file leaves this computer.', { title: ocrSource?.title ?? t('a PDF') }) : t(attachedOnly ? 'Read the attached PDFs, then write a source-linked answer.' : 'Download the open-access PDFs of the included sources, then write a source-linked answer.')}</p></div>
        </div>}
        <ol className="chat-steps">{order.map((key, i) => {
        const state = stateOf(i)
        if (collapsed && idle(state)) return null
        const group = groups[i]
        const seconds = phaseSeconds(group, state)
        const text = detail(key, state, group)
        const hasQueries = key === 'search' && (searches.length > 0 || Boolean(runningSearch && active))
        const hasConcepts = key === 'plan' && state === 'done' && Boolean(plan?.concepts.length)
        const note = report(key, state, group)
        const hasDetails = hasQueries || hasConcepts || Boolean(note)
        // Closed by default; a search in progress shows its queries so the live row can be read.
        const detailsOpen = openPhases[key] ?? (run.kind === 'review' || hasQueries && state === 'running')
        // A search that did not complete belongs to the search line itself, in the attention colour, not to a paragraph after the run (D18).
        const missed = key === 'search' ? failedProviders : []
        return <li key={key} className={`chat-step is-${state}`}>
          <div className="chat-step-line">
            <span className="chat-step-icon" role="img" aria-label={t(state === 'done' ? 'Done' : state === 'running' ? 'In progress' : state === 'attention' ? 'Stopped here' : state === 'waiting' ? 'Waiting' : 'Not run')}>
              {state === 'done' ? <Check size={13} strokeWidth={2.5} /> : state === 'running' ? <LoaderCircle size={14} className="chat-spin" /> : state === 'attention' ? <TriangleAlert size={13} /> : state === 'skipped' ? <Minus size={13} /> : null}
            </span>
            <span className="chat-step-main">
              {hasDetails
                ? <button type="button" className="chat-step-title" aria-expanded={detailsOpen} onClick={() => setOpenPhases({ ...openPhases, [key]: !detailsOpen })}><span className={state === 'running' ? 'shimmer-text' : undefined}>{title(key, state, group)}</span>{detailsOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}</button>
                : <span className={`chat-step-title${state === 'running' ? ' shimmer-text' : ''}`}>{title(key, state, group)}</span>}
              {(text || missed.length > 0) && <small>{text}{text && missed.length ? ' · ' : ''}
                {missed.length > 0 && <em className="chat-step-missed">{missed.map(([id]) => <ConnectionIcon key={id} id={id} />)}{t('{list} did not complete', { list: missed.map(([, name]) => name).join(', ') })}</em>}</small>}
            </span>
            <time>{seconds === null ? '' : durationText(seconds)}</time>
          </div>
          {key === 'plan' && adviceLines}
          {collapsed && state === 'running' && <div className="chat-step-progress">
            <span className="chat-step-progress-bar"><span style={{ width: `${Math.round(((i + 0.5) / order.length) * 100)}%` }} /></span>
            <small>{t('stage {n} of {total}', { n: i + 1, total: order.length })}</small>
          </div>}
          {note && detailsOpen && <div className="chat-step-note">{note}</div>}
          {hasConcepts && detailsOpen && <ul className="chat-list">
            {plan?.concepts.map(c => <li key={c.label}>
              <span className="chat-list-text"><b>{c.label}</b>{c.synonyms.length ? ` · ${c.synonyms.join(', ')}` : ''}</span>
              <small>{t(c.role.replace('_', ' '))}</small>
            </li>)}
          </ul>}
          {hasQueries && detailsOpen && <ul className="chat-list">
            {/* A query read page by page has one search row per page; the list shows it once, with its pages summed. */}
            {/* When the term expansion searched too, a heading in plain words marks where each round's queries begin. */}
            {[...searches.reduce((byQuery, s) => byQuery.set(`${s.provider}\n${s.query_text}`, [...(byQuery.get(`${s.provider}\n${s.query_text}`) ?? []), s]), new Map<string, SearchRun[]>()).values()].map((pages, i, all) => {
              const s = pages[0]
              const round = s.round ?? 1
              const heading = all.some(p => (p[0].round ?? 1) > 1) && (i === 0 || (all[i - 1][0].round ?? 1) !== round)
                ? <li key={`round-${round}`} className="chat-list-round">
                  <b>{round > 1 ? <ListPlus size={13} aria-hidden /> : <Search size={13} aria-hidden />}{t(round > 1 ? 'Second search' : 'First search')}</b>
                  <span>{round > 1
                    ? run.expansion_terms?.length
                      ? t('Also searched with terms that came up in the first results: {terms}', { terms: run.expansion_terms.map(term => `“${term}”`).join(', ') })
                      : t('New terms that came up in the first results were searched as well')
                    : t('The searches planned from your question')}</span>
                </li> : null
              const failed = pages.find(p => p.status !== 'completed' && p.status !== 'zero_results')
              const count = pages.reduce((sum, p) => sum + p.result_count, 0)
              const total = pages.find(p => p.provider_total !== null)?.provider_total ?? null
              const why = rationaleOf(s.provider, s.query_text)
              return <Fragment key={s.id}>{heading}<li className={failed ? 'is-attention' : undefined}>
                <span className="chat-list-text"><code>{s.query_text}</code>{why && <small>{why}</small>}</span>
                <span className="chat-list-meta"><ConnectionIcon id={s.provider} />{providerName(s.provider)} · <b>{failed && count === 0 ? t(failed.status.replace('_', ' ')) : total === null ? plural(count, '{n} result taken', '{n} results taken') : t('{count} of {total} results taken', { count, total: compact(total) })}</b>{pages.length > 1 && <> · {plural(pages.length, '{n} page', '{n} pages')}</>}{failed && count > 0 && <> · {t(failed.status.replace('_', ' '))}</>}</span>
              </li></Fragment>
            })}
            {/* The citation chain is not a search round (D95); one line says it follows, so all three steps read in one place. */}
            {(chain || run.approval?.chaining?.enabled) && <li className="chat-list-round">
              <b><Waypoints size={13} aria-hidden />{t('Then: citation chaining')}</b>
              <span>{chain?.output?.seed_list
                ? t('The reference lists and citing papers of {seeds} papers were checked · {works} new works', { seeds: chain.output.seed_list.length, works: chain.output.new_works ?? 0 })
                : t('After screening, the reference lists and citing papers of the best matches are checked')}</span>
            </li>}
            {runningSearch && active && <li className="is-running">
              <span className="chat-list-text shimmer-text">{t('Searching')}</span>
              <span className="chat-list-meta"><LoaderCircle size={13} className="chat-spin" aria-hidden /><ConnectionIcon id={runningSearch.kind.split(':')[1] ?? ''} />{providerName(runningSearch.kind.split(':')[1] ?? '')}</span>
            </li>}
          </ul>}
        </li>
        })}
        {waitingNext.length > 0 && <li className="chat-step is-next">
          <div className="chat-step-line"><span className="chat-step-icon" aria-hidden /><span className="chat-step-main"><small>{t('Next: {list}', { list: waitingNext.join(', ') })}</small></span></div>
        </li>}</ol>
        <div className="chat-run-foot">
          {/* What ran this run and what it spent: one quiet line under the phases, not a disclosure. */}
          {(run.status !== 'queued' || run.kind === 'review') && run.kind !== 'pdf_collection' && run.kind !== 'pdf_ocr' && run.kind !== 'fulltext_fetch' && <p className="chat-run-meta">
            {models.length > 0 && <span className="chat-run-models">{models}</span>}
            {/* What the run spent sits behind one quiet toggle; the limit itself speaks only once it is reached. */}
            <button type="button" className="chat-usage-toggle" aria-expanded={usageOpen} onClick={() => setUsageOpen(!usageOpen)}>{t('Usage')}</button>
            {usageOpen && <span>{spend}</span>}
          </p>}
          {callLimitReached && <p className="chat-run-limit"><TriangleAlert size={13} aria-hidden />{t('The model call limit for this run was reached.')}</p>}
          {/* Pause, resume and cancel ride with the tabs, where every tab reaches them; the foot only opens the full ladder. */}
          {active && order.length > 1 && <button type="button" className="chat-steps-toggle" onClick={() => setAllSteps(!allSteps)}>{t(allSteps ? 'Show fewer steps' : 'Show every step')}</button>}
          {retrying && onRetryFailedSearches && <Button variant="outline" size="sm" onClick={() => void onRetryFailedSearches(run)}>
            <RotateCw size={13} />{t('Retry failed searches')}
          </Button>}
        </div>
      </>}
    </div>

    {run.status === 'paused' && run.pause_reason !== 'protocol_approval_needed' && <div className="chat-note is-warning">
      <p>{pauseReasonText(run.pause_reason)}</p>
      {pauseDetailText(run).map(line => <p key={line}>{line}</p>)}
      {run.kind === 'pdf_ocr' && failedOcrPages.length > 0 && <p>{t('Pages not read: {pages}', { pages: failedOcrPages.join(', ') })}</p>}
      {unknownSteps.length > 0 && <p>{t('Unfinished: {steps}. Resuming repeats it; a repeated model call counts against your account usage.', { steps: unknownSteps.map(s => s.kind === 'model:report_review' ? t('Report review') : stepLabel(s.kind, s.operation_key)).join(', ') })}</p>}
      {/* Code does not translate a question, so this stop is answered in the revision form and nowhere else (SW2.1). */}
      {run.pause_reason === 'key_terms_needed' && onGiveKeyTerms && <Button variant="outline" size="sm" onClick={onGiveKeyTerms}>{t('Give the English key terms')}</Button>}
      {/* Resume asks the model once more while a try is left; this button never asks it again (D92). */}
      {run.pause_reason === 'search_query_failed' && <>
        {searchQueryTriesLeft(run) === 0 && <p>{t('The model has had its second try.')}</p>}
        {onChooseCodeQuery && <Button variant="outline" size="sm" onClick={() => void onChooseCodeQuery(run)}>{t('Search with the query built from the question’s words')}</Button>}
      </>}
    </div>}
    {/* What this run would search with, before it searches: the user corrects it here and approves it (D80). */}
    {run.approval && <ProtocolApproval run={run} approval={run.approval} onApproved={() => onProtocolApproved?.()} />}
    {(run.status === 'failed' || run.status === 'cancelled') && run.pause_reason && <div className={`chat-note ${run.status === 'failed' ? 'is-error' : 'is-neutral'}`}><p>{pauseReasonText(run.pause_reason)}</p>{pauseDetailText(run).map(line => <p key={line}>{line}</p>)}</div>}
    {queueLine && <p className="chat-queue-line"><Hand size={14} aria-hidden /><span>{t(queueLine.count === 1 ? '{n} work awaits your decision' : '{n} works await your decision', { n: queueLine.count })}</span>
      <span aria-hidden>·</span><button type="button" onClick={queueLine.open}>{t('Open')}</button></p>}
    {children}
    {!children && answer && run.kind === 'answer' && <div className="answer-history-note"><span className="answer-history-icon" aria-hidden="true"><TriangleAlert size={14} /></span><span>{t('An earlier answer: {status}.', { status: t(answer.status.replaceAll('_', ' ')) })}</span></div>}
  </section>
}

// The citation chain of one discovery run (D95): what it asked, what it kept, and the seeds it started from, which
// open under the line. Counted from the chain's own steps, so a resumed run reads the same.
function ChainReport({ steps, view }: { steps: Step[]; view: ResearchView }) {
  const [open, setOpen] = useState(false)
  const chainSteps = steps.filter(s => s.kind.startsWith('code:chain_') || s.kind.startsWith('provider_chain:') || s.operation_key.startsWith('abstract_screening:chain:'))
  const summary = steps.find(s => s.kind === 'code:chain_summary')?.output ?? {}
  const seeds = summary.seed_list ?? []
  const starts = present(chainSteps.map(s => s.started_at))
  const ends = present(chainSteps.map(s => s.finished_at))
  const seconds = starts.length && ends.length ? secondsBetween(starts[0], Date.parse(ends[ends.length - 1])) : null
  const requests = summary.requests ?? {}
  const s2 = summary.semantic_scholar
  const titleOf = (svid: string) => view.sources.find(s => s.source_version_id === svid)?.title ?? svid
  const line = [
    plural(seeds.length, 'Checked the reference lists and citing papers of {n} paper', 'Checked the reference lists and citing papers of {n} papers'),
    plural(requests.sent ?? 0, '{n} lookup', '{n} lookups'),
    plural(summary.new_works ?? 0, '{n} new work', '{n} new works'),
    plural(summary.read_by_model ?? 0, '{n} abstract read by the model', '{n} abstracts read by the model'),
    requests.failed ? plural(requests.failed, '{n} lookup did not complete', '{n} lookups did not complete') : '',
    requests.not_reached_seeds ? plural(requests.not_reached_seeds, '{n} paper not reached (request limit)', '{n} papers not reached (request limit)') : '',
    s2?.status === 'skipped' ? t('Semantic Scholar skipped ({reason})', { reason: t(s2.reason === 'not_configured' ? 'not configured' : 'not in the research sources') }) : '',
    s2?.seeds_without_doi ? plural(s2.seeds_without_doi, '{n} paper without a DOI was not looked up in Semantic Scholar', '{n} papers without a DOI were not looked up in Semantic Scholar') : '',
  ].filter(Boolean).join(' · ')
  return <>
    <p className="chat-report-line">
      <button type="button" className="chat-step-title" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>{line}</span>{open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
      </button>
      {seconds !== null && <time>{durationText(seconds)}</time>}
    </p>
    {open && <ul className="chat-list">
      {seeds.map(seed => <li key={seed.source_version_id}>
        <span className="chat-list-text">{titleOf(seed.source_version_id)}</span>
        <small>{t(seed.kind === 'user' ? 'your seed' : 'ranking seed')}</small>
      </li>)}
    </ul>}
  </>
}
