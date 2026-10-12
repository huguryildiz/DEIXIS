import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, BookOpen, Check, ChevronDown, ChevronRight, FileText, ListChecks, LoaderCircle, Minus, Pause, PencilLine, Play, RotateCw, ScanText, Search, ShieldCheck, Sparkles, TriangleAlert, Waypoints, type LucideIcon } from 'lucide-react'
import { api, type ResearchView, type Run, type Verdict, type ReviewCard, type ReviewTargetKind, type SearchRun } from './api'
import { ocrLanguagesText as ocrLanguages } from './ocr'
import { serviceWaitRecordText, providerRetryText, serviceErrorSentence, serviceKind, connectionName, failedSectionReasonText, fetchReasonText, pauseDetailText, pauseReasonText, providerName, approvedByText, runStatusLabels, searchQueryTriesLeft, seedUseText, stepLabel, verdictLabels } from './labels'
import { ConnectionIcon } from './connectionIcons'
import { ArmReport, NotFoundReport, SignalReport } from './ProbeTables'
import { ModelName } from './ModelName'
import { effortLabels } from './Home'
import { AnswerFlowNote } from './FlowReport'
import type { ModelText } from './modelText'
import { t, uiLocale } from './i18n'
import { scrollBehavior } from './motion'
import { Button } from '@/components/ui/button'

// The research as a record of work: one turn per run, each run one line per phase (mockup `.steps`, R14), details one
// click deeper (R15). The page's event stream refreshes the view; a one-second clock keeps running durations moving.
// Pause sits beside the run chip in the topbar; Resume run and Cancel run sit in the notice under a stopped run's steps (R18).

type PhaseKey = 'plan' | 'search' | 'chain' | 'screen' | 'pdf' | 'ocr' | 'semantic' | 'answer' | 'review' | 'sections' | 'assembly'
type PhaseState = 'done' | 'running' | 'attention' | 'waiting' | 'skipped'
type Step = NonNullable<Run['steps']>[number]

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
// Title while running, once done, and before the phase starts or when it is not run.
const titles: Record<PhaseKey, [string, string, string]> = {
  plan: ['Planning the searches', 'Planned the searches', 'Search plan'],
  search: ['Searching the providers', 'Searched the providers', 'Provider searches'],
  chain: ['Following citations from the strongest matches', 'Followed one round of citations', 'Citation chaining'],
  screen: ['Screening the candidates', 'Screened the candidates', 'Screening'],
  pdf: ['Downloading open-access PDFs', 'Downloaded open-access PDFs', 'Open-access PDFs'],
  ocr: ['Reading scanned pages with OCR', 'Read scanned pages with OCR', 'OCR of scanned pages'],
  semantic: ['Preparing semantic search', 'Prepared semantic search', 'Semantic search'],
  answer: ['Writing the answer', 'Wrote the answer', 'Source-linked answer'],
  review: ['Reviewing the claims', 'Reviewed the claims', 'Claim review'],
  sections: ['Writing sections', 'Wrote the sections', 'Report sections'],
  assembly: ['Checking the assembled report', 'Checked the assembled report', 'Assembled report'],
}
// The mockup's icon of each phase (18px box); a live phase shows the spinner, a stopped one the warning sign.
const phaseIcons: Record<PhaseKey, LucideIcon> = { plan: PencilLine, search: Search, chain: Waypoints, screen: ListChecks, pdf: BookOpen, ocr: ScanText,
  semantic: Sparkles, answer: FileText, review: ShieldCheck, sections: FileText, assembly: ShieldCheck }
// What a stopped phase was doing, for "Paused while …" / "Stopped while …".
const doingNames: Record<PhaseKey, string> = { plan: 'planning', search: 'searching', chain: 'following citations', screen: 'screening',
  pdf: 'reading full texts', ocr: 'reading scanned pages', semantic: 'preparing semantic search', answer: 'writing the answer',
  review: 'checking citations', sections: 'writing sections', assembly: 'checking the report' }
// A phase not reached yet, as the "Next:" line names it.
const nextNames: Record<PhaseKey, string> = { plan: 'plan the searches', search: 'search the providers', chain: 'follow citations',
  screen: 'screen abstracts', pdf: 'read full texts', ocr: 'read scanned pages', semantic: 'prepare semantic search',
  answer: 'write a source-linked answer', review: 'check citations', sections: 'write the sections', assembly: 'check the report' }
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
  if (kind === 'model:search_plan' || kind === 'model:search_query') return 'plan'
  // An sw run plans its search in code before it searches; those steps are its plan phase.
  if (['code:vocabulary', 'model:vocabulary_labels', 'model:criterion_proposal', 'code:criterion', 'code:protocol_approval'].includes(kind)) return 'plan'
  if (kind.startsWith('provider_search')) return 'search'
  if (kind === 'model:screening') return 'screen'
  // An sw run screens abstracts in two steps: code classifies every record, then the model proposes.
  if (kind === 'code:abstract_stage' || kind === 'model:abstract_screening') return 'screen'
  // The fast chain's requests are not searches of the question; they are the run's citation-chaining phase (D95).
  if (kind.startsWith('provider_chain:') || kind.startsWith('code:fast_chain') || kind === 'code:chain_filter' || kind === 'code:chain_record_flags') return 'chain'
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
export function Transcript({ view, emptyText, latestAnswer, modelText, onRetryFailedSearches, onGiveKeyTerms, onChooseCodeQuery, queueCount = 0, onOpenQueue, onOpenPdfs, onControlRun, onRewrite, busy = false }: {
  view: ResearchView; emptyText: string; latestAnswer: ReactNode; modelText: ModelText
  onRetryFailedSearches?: (run: Run) => Promise<void>
  // Resume run and Cancel run of the notice under a stopped run's steps (R18); Pause stays in the topbar.
  onControlRun?: (run: Run, action: 'resume' | 'cancel') => void
  // The too-broad notice (R21): the rewritten question is saved as a new revision, which then searches.
  onRewrite?: (question: string) => Promise<void>
  // The reading step's "Get more full text" link opens the PDFs panel.
  onOpenPdfs?: () => void
  busy?: boolean
  // The way out of a `key_terms_needed` stop: the revision form in the question bubble, on its key-terms field.
  onGiveKeyTerms?: () => void
  // The way on after the model could not write the query: search with the code's query alone (D92).
  onChooseCodeQuery?: (run: Run) => Promise<void>
  // An sw research's works awaiting a person, named once under the latest reading run (slice 17).
  queueCount?: number; onOpenQueue?: () => void
}) {
  const runs = [...view.runs].reverse()  // the view lists the newest run first
  // The turn that names the works awaiting a decision: the current question's latest search, whose screening step
  // shows them (S9); without one, the reading run, or a small-batch discovery run (D237), which reads inside itself.
  const lastReading = runs.filter(r => r.kind === 'fulltext_adjudication'
    || (r.kind === 'discovery' && (r.budget as unknown as { inspection?: { policy?: string } } | null)?.inspection?.policy === 'small_batch_fused_v1')).at(-1)?.id
  const active = runs.some(r => ACTIVE.has(r.status))
  // The steps stay open for the current question's latest search and the latest answer, so the thread reads as one list
  // of phases from the plan to the citation check; earlier runs fold to their heading.
  const latestAnswerRun = runs.filter(r => r.kind === 'answer').at(-1)?.id
  const latestDiscovery = view.runs.find(r => r.kind === 'discovery' && r.scope_revision === view.research.current_scope_revision)?.id
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
  // The current question opens the thread as the user's turn (ResearchView's question bubble, S8).
  return <>
  <div className={`chat${runs.length ? '' : ' is-empty'}`}>
    {runs.map((run, i) => <RunTurn key={run.id} run={run} view={view} now={now} latest={i === runs.length - 1} keepOpen={run.id === latestAnswerRun || run.id === latestDiscovery}
      modelText={modelText} onRetryFailedSearches={onRetryFailedSearches} onGiveKeyTerms={onGiveKeyTerms} onChooseCodeQuery={onChooseCodeQuery}
      onControlRun={onControlRun} onRewrite={onRewrite} onOpenPdfs={onOpenPdfs} busy={busy}
      queueLine={run.id === (latestDiscovery ?? lastReading) && queueCount > 0 && onOpenQueue ? { count: queueCount, open: onOpenQueue } : null}>
      {view.answers[0]?.run_id === run.id ? latestAnswer : null}
    </RunTurn>)}
    {!runs.length && <div className="chat-say"><Sparkles size={18} strokeWidth={1.6} aria-hidden /><p>{emptyText}</p></div>}
    <div ref={end} className="chat-end" />
    {active && !atEnd && <button type="button" className="chat-jump" onClick={() => end.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'end' })}><ArrowDown size={15} aria-hidden />{t('Jump to latest')}</button>}
  </div>
  </>
}

function RunTurn({ run, view, now, latest, keepOpen, modelText, onRetryFailedSearches, onGiveKeyTerms, onChooseCodeQuery, onControlRun, onRewrite, onOpenPdfs, busy, queueLine = null, children }: {
  run: Run; view: ResearchView; now: number; latest: boolean; keepOpen: boolean; modelText: ModelText
  onRetryFailedSearches?: (run: Run) => Promise<void>
  onGiveKeyTerms?: () => void
  onChooseCodeQuery?: (run: Run) => Promise<void>
  onControlRun?: (run: Run, action: 'resume' | 'cancel') => void
  onRewrite?: (question: string) => Promise<void>
  onOpenPdfs?: () => void
  busy: boolean
  queueLine?: { count: number; open: () => void } | null; children: ReactNode
}) {
  const active = ACTIVE.has(run.status)
  const [open, setOpen] = useState<boolean | null>(null)
  // Each phase reads as one line; what it found (plan text, concepts, queries, counts) opens under it on request.
  const [openPhases, setOpenPhases] = useState<Partial<Record<PhaseKey, boolean>>>({})
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
  // A finished run folds away once something follows it; the current question's latest search and the latest answer stay open.
  const expanded = open ?? (run.status !== 'completed' || keepOpen)
  const clock = active ? Math.max(now, Date.parse(run.updated_at)) : Date.parse(run.updated_at)

  const steps = run.steps ?? []
  // An sw discovery run queued since slice 17a fetches the full text itself, beside its screening.
  const overlap = run.kind === 'discovery' && (run.budget.fulltext_fetch as unknown as { mode?: string } | undefined)?.mode === 'overlap'
  // The answer the fast path writes from discovery's evidence fetches nothing and ranks nothing: it answers, then its
  // citations are checked. An answer over attached PDFs reads them and ranks their passages first.
  const boundAnswer = run.kind === 'answer' && Boolean((run.budget as unknown as { fast_path?: unknown }).fast_path)
  const order: PhaseKey[] = run.kind === 'review' ? ['review'] : run.kind === 'report' ? ['plan', 'sections', 'assembly'] : run.kind === 'discovery' ? discoveryOrder(run) : run.kind === 'pdf_collection' || run.kind === 'fulltext_fetch' || run.kind === 'fulltext_adjudication' ? ['pdf'] : run.kind === 'pdf_ocr' ? ['ocr'] : [...(boundAnswer ? [] : ['pdf' as const, 'semantic' as const]), 'answer', 'review']
  const groups = order.map(key => steps.filter(s => phaseOf(s.kind) === key))
  const reached = run.kind === 'report' && !active ? 2 : Math.max(order.indexOf(stagePhases[run.stage]), ...groups.map((group, i) => (group.length ? i : -1)))
  // A citation chain's requests are not searches of the question; the chaining phase reports them (D95).
  // The funnel counts belong to the current question revision; only its latest discovery run may show them (D233).
  const latestDiscovery = run.kind === 'discovery' && view.runs.find(r => r.kind === 'discovery' && r.scope_revision === view.research.current_scope_revision)?.id === run.id
  const searches = view.search_runs.filter(s => s.run_id === run.id && !s.query_text.startsWith('chain:'))
  const answer = view.answers.find(a => a.run_id === run.id)
  const started = present(steps.map(s => s.started_at))[0] ?? run.created_at
  // A call cut at a read deadline (D258) is closed for good: resuming does not repeat it.
  const unknownSteps = steps.filter(s => s.status === 'outcome_unknown' && s.error_code !== 'model_read_cutoff')
  const failedOcrPages = steps.filter(s => s.kind === 'ocr_page' && troubled(s)).map(s => s.operation_key.split(':')[2])
  // A failed search no longer stops the run (D18); name the provider that is missing so the results are not read as
  // complete. Why it failed stays on its query row in the phase details, where the other provider results are.
  const failedProviders = [...new Map(steps.filter(s => s.kind.startsWith('provider_search') && troubled(s))
    .map(s => [s.kind.split(':')[1] ?? '', providerName(s.kind.split(':')[1] ?? '')])).entries()]
  const retrying = run.kind === 'discovery' && !active && (run.status === 'completed' || run.status === 'paused')
    && steps.some(s => s.kind.startsWith('provider_search') && troubled(s))
  // The screening the run itself proposed on, and the sources the answer run reads.
  const screened = view.sources.filter(s => s.found_in_revision === run.scope_revision)
  const included = view.sources.filter(s => s.selection.state === 'included')
  // The similarity step belongs to no phase of its own; the screening phase reports it.
  const similarity = steps.find(s => s.kind.startsWith('similarity:'))
  // What the fast chain did in this run, once its summary is written: the works it started from (the semantic search's
  // seeds and any the ranking added) and the works no keyword search of the run found.
  const chainDone = steps.some(s => s.operation_key === 'fast_chain:summary' && s.status === 'succeeded')
  const chainSeeds = steps.reduce((sum, s) => sum + (s.kind === 'code:fast_chain' ? s.output?.seed_count ?? 0 : 0), 0)
  const chainNew = run.source_counts?.counted ? run.source_counts.chain?.only : undefined
  // What became of the fast chain's requests, counted by the backend (`chaining.request_outcomes`, the rule the report's
  // method section uses): sent requests answered in time, after the cutoff (works not kept), failed or with an unknown
  // outcome; requests never sent; and unknown outcomes with no record that they were sent.
  const requests = run.chain_requests
  const chainLine = [
    plural(chainSeeds, '{n} seed paper chosen', '{n} seed papers chosen'),
    requests ? plural(requests.sent, '{n} request sent', '{n} requests sent') : '',
    requests?.answered ? plural(requests.answered, '{n} request answered', '{n} requests answered') : '',
    requests?.late ? plural(requests.late, '{n} answered after the cutoff, its works not kept', '{n} answered after the cutoff, their works not kept') : '',
    requests?.failed ? plural(requests.failed, '{n} request failed', '{n} requests failed') : '',
    requests?.unknown ? plural(requests.unknown, '{n} request with an unknown outcome', '{n} requests with an unknown outcome') : '',
    requests?.not_sent ? plural(requests.not_sent, '{n} request not sent', '{n} requests not sent') : '',
    requests?.unproven ? plural(requests.unproven, '{n} request with an unknown outcome, not known to be sent', '{n} requests with an unknown outcome, not known to be sent') : '',
    chainNew === undefined ? '' : plural(chainNew, '{n} new work', '{n} new works'),
  ].filter(Boolean).join(' · ')
  // A pdf_ocr run (D51): its PDF, the pages without text it found, and what became of the merged text.
  const ocrSource = run.kind === 'pdf_ocr' ? view.sources.find(s => s.source_version_id === run.target?.source_version_id) : undefined
  const ocrAsset = ocrSource?.access.assets.find(a => a.id === run.target?.asset_id)
  const ocrPages = steps.find(s => s.kind === 'ocr_pages')?.output?.image_pages

  // With the fetch beside it, screening is over only once its final retrieval plan is written; both phases can run at once.
  const fetchPlanned = steps.some(s => s.kind === 'code:fulltext_plan' && s.status === 'succeeded')
  const fetchSummary = steps.find(s => s.kind === 'code:fulltext_summary' && s.status === 'succeeded')?.output
  const fetchWorks = steps.filter(s => s.kind === 'code:fulltext_work')
  const stateOf = (i: number): PhaseState => {
    if (run.kind === 'review' && ownerReview && ['partial', 'failed', 'cancelled', 'paused'].includes(ownerReview.card.state)) return 'attention'
    if (run.kind === 'report' && order[i] === 'assembly') return active ? 'waiting' : run.status === 'completed' ? 'done' : 'attention'
    if (run.kind === 'report' && order[i] === 'sections' && run.status === 'paused') return 'attention'
    // An answer's citations are checked in code when it is validated: every anchor of a valid answer was located in its
    // passage. A reviewer model's claim review, when one ran in this run, is part of the same phase.
    if (run.kind === 'answer' && order[i] === 'review' && !groups[i].length) {
      if (answer?.status === 'structurally_valid') return 'done'
      return active || run.status === 'paused' ? 'waiting' : 'skipped'
    }
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
      case 'plan':
        return attemptText
      case 'search': {
        if (!searches.length) return ''
        // The line keeps the totals only; the per-provider figures are in the phase details, on the query rows.
        const found = searches.reduce((sum, s) => sum + (s.status === 'completed' ? s.result_count : 0), 0)
        // Unique works are counted per question revision, not per run, so they are named only on the latest discovery run
        // of the current revision (D233). These are rows the providers returned, not sources found.
        const funnel = latestDiscovery ? view.counts.funnel : null
        if (funnel) return [t('{retrieved} records retrieved by search', { retrieved: funnel.retrieved.toLocaleString(uiLocale()) }),
          ...(funnel.chained ? [t('{chained} works added by citation chaining', { chained: funnel.chained.toLocaleString(uiLocale()) })] : []),
          t('{unique} unique works', { unique: funnel.unique.toLocaleString(uiLocale()) })].join(' · ')
        return plural(found, '{n} record retrieved', '{n} records retrieved')
      }
      case 'screen': {
        if (state === 'running') {
          // Abstracts the model has read: each batch is read twice, so a work counts once however many reads of it are done.
          const read = new Set(group.flatMap(s => s.kind === 'model:abstract_screening' && s.status === 'succeeded' ? s.output?.candidate_ids ?? [] : [])).size
          const stages = group.filter(s => s.kind === 'code:abstract_stage' && s.output?.batch_sizes)
          const total = stages.reduce((sum, s) => sum + (s.output?.batch_sizes ?? []).reduce((a, b) => a + b, 0), 0)
          // Without the code's list of what it queued, no total is claimed.
          if (!stages.length) return read ? plural(read, '{n} abstract read', '{n} abstracts read') : ''
          return t('{read} of {total} abstracts read', { read, total })
        }
        const outcome = t('{included} included · {excluded} excluded · {pending} undecided', { included: view.counts.included, excluded: view.counts.excluded, pending: view.counts.pending })
        // The funnel, from the provider rows down to the included works (D233). A candidate passed the abstract stage; it is not called relevant.
        const funnel = latestDiscovery ? view.counts.funnel : null
        return funnel ? [outcome, t('{read} abstracts read · {candidates} candidates', { read: funnel.abstracts_read.toLocaleString(uiLocale()), candidates: funnel.candidates.toLocaleString(uiLocale()) }),
          t('out of {unique} unique works', { unique: funnel.unique.toLocaleString(uiLocale()) })].join(' · ') : outcome
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
        // The works each source brought after the DOI and work merge, and how many no other source did (D93). A run
        // whose counts were not kept says so instead of showing zeros.
        const counts = run.source_counts
        // An sw research's rows also carry what each arm found that was later included or confirmed (slice 19).
        const arms = counts?.counted && counts.arms ? <ArmReport counts={counts} probes={view.probes}
          modelTerms={Boolean(run.approval?.approved?.terms.some(term => term.origin === 'model'))} /> : null
        // The person's works no search of this question revision found, under its latest discovery run.
        const notFound = view.probes && view.runs.find(r => r.kind === 'discovery' && r.scope_revision === view.research.current_scope_revision)?.id === run.id
          ? <NotFoundReport probes={view.probes} /> : null
        const perSource = !arms && counts && (counts.counted
          ? counts.sources.length > 0 && <p className="chat-provider-totals">
            {counts.sources.map(source => <span key={source.provider_id}>
              <ConnectionIcon id={source.provider_id} />{providerName(source.provider_id)} {t('{works} works, {only} no other source’s search found', { works: source.works, only: source.only })}
            </span>)}</p>
          : <p className="chat-report-line"><span>{t('Works per source were not counted for this run')}</span></p>)
        // A single provider is already named on each query row below.
        const totals = perProvider.size < 2 ? null : <p className="chat-provider-totals">{[...perProvider].map(([id, { taken, total }]) => <span key={id}>
          <ConnectionIcon id={id} />{providerName(id)} {total !== null && total > taken ? t('{count} of {total}', { count: taken, total: compact(total) }) : taken}
        </span>)}</p>
        if (!totals && !perSource && !arms && !notFound) return null
        return <>{totals}{perSource}{arms}{notFound}</>
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
  // Live runs read as one line per phase: what the run has not reached yet is named once in the "Next:" line, and what it
  // skips stays out (mockup `.steps`, R14 and R16).
  const phaseStates = order.map((_, i) => stateOf(i))
  const collapsed = active && phaseStates.some(state => state === 'waiting')
  const busyEquationPdfs = new Set(steps.filter(step => step.kind === 'read_equations' && step.output?.outcome === 'file_busy').map(step => step.output?.asset_id)).size

  // The numbers the step lines and details name, each from a stored record of this run or of this question revision.
  const funnel = latestDiscovery ? view.counts.funnel ?? null : null
  const fiveCounts = latestDiscovery ? view.counts.flow?.five ?? null : null
  const flowBuckets = latestDiscovery ? view.counts.flow?.buckets ?? null : null
  const notScreened = flowBuckets?.not_screened ?? null
  const listFormat = (names: string[]) => new Intl.ListFormat(uiLocale(), { type: 'conjunction' }).format(names)
  const searchedProviders = listFormat([...new Set([...searches.map(s => s.provider), ...steps.filter(s => s.kind.startsWith('provider_search:')).map(s => s.kind.split(':')[1] ?? '')])].filter(Boolean).map(providerName))
  // Each abstract the model read, by how many successful reads it had: the fast path reads every batch twice.
  const abstractReads = new Map<string, number>()
  steps.filter(s => s.kind === 'model:abstract_screening' && s.status === 'succeeded').forEach(s => (s.output?.candidate_ids ?? []).forEach((id: string) => abstractReads.set(id, (abstractReads.get(id) ?? 0) + 1)))
  const readTwice = abstractReads.size > 0 && [...abstractReads.values()].every(n => n >= 2)
  const evidence = answer?.claims.flatMap(c => c.evidence) ?? []
  const citedSources = new Set(evidence.map(e => e.source_version_id)).size
  const citedPassages = new Set(evidence.map(e => e.passage_id)).size
  const similarityScored = Boolean(similarity && similarity.kind !== 'similarity:off' && (similarity.status === 'succeeded' || similarity.status === 'partial'))
  const fastPath = (run.budget as unknown as { fast_path?: { K?: number; mode?: string; auto_answer?: boolean; ledger_run_id?: string } }).fast_path
  // Stage N of M counts the fast path's whole sequence: a discovery run that queues its answer by itself counts the
  // answer and its citation check too, and that answer continues the count of the discovery it answers from (R16).
  const autoAnswer = run.kind === 'discovery' && fastPath?.auto_answer === true
  const ledger = boundAnswer && fastPath?.ledger_run_id ? view.runs.find(r => r.id === fastPath.ledger_run_id) : undefined
  const stageOffset = ledger ? discoveryOrder(ledger).length : 0
  const stageTotal = stageOffset + order.length + (autoAnswer ? 2 : 0)

  // What a stopped phase says: where the run stood when it paused, stopped or was cancelled.
  const stopText = (key: PhaseKey) => {
    if (key === 'plan' && run.pause_reason === 'vocabulary_too_broad') return t('Stopped while planning: the question is too broad')
    if (key === 'plan' && run.pause_reason === 'vocabulary_empty') return t('Stopped while planning: no search term could be built from the question')
    const doing = t(doingNames[key])
    return run.status === 'cancelled' ? t('Cancelled while {doing}', { doing }) : run.status === 'paused' && run.pause_reason === 'user_requested' ? t('Paused while {doing}', { doing }) : t('Stopped while {doing}', { doing })
  }
  // The line of a phase (mockup step copy for the search and answer phases; the other runs keep their own words).
  const lineText = (key: PhaseKey, state: PhaseState, group: Step[]): string => {
    const fallback = () => [title(key, state, group), detail(key, state, group)].filter(Boolean).join(' · ')
    if (run.kind !== 'discovery' && !(run.kind === 'answer' && (key === 'answer' || key === 'review'))) return fallback()
    if (state === 'attention' && run.status !== 'completed') return stopText(key)
    const live = state === 'running'
    const ongoing = (text: string, progress = '') => [`${text}…`, progress].filter(Boolean).join(' · ')
    switch (key) {
      case 'plan':
        if (live) return ongoing(t('Planning the searches from the question'), detail(key, state, group))
        return t(run.approval?.approved_by === 'user' ? 'Planned the searches from your saved plan' : 'Planned the searches from the question’s words')
      case 'search':
        if (live) return ongoing(searchedProviders ? t('Searching {providers}', { providers: searchedProviders }) : t('Searching the providers'))
        if (!searches.length) return fallback()
        return [t('Searched {providers}', { providers: searchedProviders }), funnel ? plural(funnel.unique, '{n} unique work', '{n} unique works', { n: funnel.unique.toLocaleString(uiLocale()) })
          : plural(searches.reduce((sum, s) => sum + (s.status === 'completed' ? s.result_count : 0), 0), '{n} record retrieved', '{n} records retrieved')].join(' · ')
      case 'chain':
        if (live) return ongoing(t('Following citations from the strongest matches'))
        return [t('Followed one round of citations'), chainNew === undefined ? '' : [plural(chainNew, '{n} work added', '{n} works added'),
          funnel ? t('{n} in the pool', { n: funnel.unique.toLocaleString(uiLocale()) }) : ''].filter(Boolean).join(', ')].filter(Boolean).join(' · ')
      case 'screen': {
        if (live) return ongoing(t('Screening abstracts against the criterion'), detail(key, state, group))
        const read = funnel?.abstracts_read ?? abstractReads.size
        if (!read) return fallback()
        const screenedText = t(readTwice ? 'Screened {n} abstracts twice' : 'Screened {n} abstracts', { n: read.toLocaleString(uiLocale()) })
        if (!funnel) return screenedText
        // A candidate passed the abstract stage; nothing is called relevant, and an abstract alone includes nothing. The
        // out-of-scope count is the flow's own bucket: read minus passed is not it, as the funnel's candidates also count
        // works code let through without a read.
        const outOfScope = flowBuckets ? flowBuckets.out_of_scope_model + flowBuckets.out_of_scope_code : null
        const passed = funnel.candidates.toLocaleString(uiLocale())
        return [screenedText, outOfScope === null ? t('{n} passed the abstract stage', { n: passed })
          : t('{passed} passed the abstract stage, {out} out of scope', { passed, out: outOfScope.toLocaleString(uiLocale()) })].join(' · ')
      }
      case 'pdf': {
        if (!group.some(s => s.kind === 'model:fulltext_adjudication' || s.kind === 'code:adjudication_plan')) return fallback()
        const { done, total } = readingWorks(group)
        if (live) return ongoing(t('Reading full texts of works that passed the abstract stage'), t('{done} of {total} works', { done, total }))
        // §2.3: the reading takes selected pages of each PDF, not the whole text.
        return [plural(done, 'Read {n} work in its full text (selected pages)', 'Read {n} works in their full text (selected pages)'),
          fiveCounts?.not_read_not_tried ? t('{n} passed the abstract stage, full text not tried', { n: fiveCounts.not_read_not_tried }) : ''].filter(Boolean).join(' · ')
      }
      case 'answer':
        if (live) return ongoing(t('Writing a source-linked answer'))
        if (answer?.status !== 'structurally_valid') return fallback()
        return [t('Wrote a source-linked answer'), t('{claims} claims from {sources} sources', { claims: answer.claims.length, sources: citedSources })].join(' · ')
      case 'review':
        if (group.length) return fallback()
        if (live) return ongoing(t('Checking every citation against its passage'))
        return [t('Checked citations'), t('{located} of {total} anchors located in their passages', { located: evidence.length, total: evidence.length })].join(' · ')
      default:
        return fallback()
    }
  }

  // One detail row: a label and its value, as the mockup's `.step-detail .row`.
  const row = (label: ReactNode, value: ReactNode, key?: string) => <div className="step-row" key={key}><span>{label}</span><span className="step-row-value">{value}</span></div>
  const searchRows = () => {
    // A query read page by page has one search row per page; the row shows it once, with its pages summed. The semantic
    // search sends the question itself; the keyword queries are numbered as the plan lists them.
    const keywordTexts = [...new Set([...(run.approval?.approved.queries ?? []).map(q => q.query_text), ...searches.map(s => s.query_text)])]
      .filter(text => text !== view.scope.question && text !== view.semantic?.english_question?.text)
    return [...searches.reduce((byQuery, s) => byQuery.set(`${s.provider}\n${s.query_text}`, [...(byQuery.get(`${s.provider}\n${s.query_text}`) ?? []), s]), new Map<string, SearchRun[]>()).values()].map(pages => {
      const s = pages[0]
      const failed = pages.find(p => p.status !== 'completed' && p.status !== 'zero_results')
      const count = pages.reduce((sum, p) => sum + p.result_count, 0)
      const total = pages.find(p => p.provider_total !== null)?.provider_total ?? null
      const retryCount = pages.reduce((sum, page) => sum + (page.error?.retries ?? 0), 0)
      const kind = keywordTexts.includes(s.query_text) ? t('keyword, query {n}', { n: keywordTexts.indexOf(s.query_text) + 1 }) : t('semantic')
      return <div key={s.id} className={`step-row${failed ? ' is-attention' : ''}`}>
        <span><ConnectionIcon id={s.provider} />{providerName(s.provider)} · {kind}</span>
        <span className="step-row-value">{failed && count === 0 ? t(failed.status.replace('_', ' ')) : total === null ? t('{n} taken', { n: count.toLocaleString(uiLocale()) }) : t('{count} of {total} taken', { count: count.toLocaleString(uiLocale()), total: total.toLocaleString(uiLocale()) })}{pages.length > 1 && <> · {plural(pages.length, '{n} page', '{n} pages')}</>}{failed && count > 0 && <> · {t(failed.status.replace('_', ' '))}</>}{retryCount > 0 && <> · {providerRetryText(retryCount)}</>}</span>
      </div>
    })
  }
  const chainRecords = (direction: string) => view.search_runs.filter(s => s.run_id === run.id && s.query_text.startsWith('chain:') && s.query_text.includes(`:${direction}:`)).reduce((sum, s) => sum + s.result_count, 0)
  const modelRow = (label: string, agent: { connection: string; model: string | null; effort: string | null } | undefined) => agent?.model ? row(t(label), <ModelName connection={agent.connection} text={modelText(agent.model, agent.effort)} />) : null

  // What the finished phase found (R15): the plan, the queries and their counts, the chain, the screening, the reading,
  // the answer's inputs and its citation check, each from stored records; then the existing report lines of the phase.
  const stepDetail = (key: PhaseKey, state: PhaseState, group: Step[], seconds: number | null): ReactNode => {
    const note = report(key, state, group)
    const parts: ReactNode[] = []
    if (key === 'plan' && run.kind === 'discovery') {
      const approved = run.approval?.approved
      const words = approved?.terms.filter(term => !term.dropped).map(term => term.phrase) ?? []
      const queries = [...new Map((approved?.queries ?? []).map(q => [q.query_text, q])).values()]
      if (words.length) parts.push(<div key="words">{t('Search words')}: {words.map(word => <code key={word}>{word}</code>)}</div>)
      // Each provider gets its own query text; with more than one provider the row names whose query it is.
      const severalProviders = new Set(queries.map(q => q.provider_id)).size > 1
      // The query text follows its label on the row, wrapping under it when long (mockup `.row` with a `code`).
      queries.forEach((query, i) => parts.push(<div key={`query-${i}`} className="step-row"><span>{t('Query {n}', { n: i + 1 })}{severalProviders && <> · {providerName(query.provider_id)}</>}{query.origin && <> · {t(query.origin === 'model' ? 'model' : query.origin === 'user' ? 'your plan' : 'from the question’s words')}</>}</span><code>{query.query_text}</code></div>))
      if (approved?.criterion?.criterion) parts.push(<div key="criterion" className="step-row"><span>{t('Inclusion criterion')}</span><span className="step-row-text">{approved.criterion.criterion}</span></div>)
      // The English sentence the semantic search sent, and the PDFs that guided the search (§2.2), for the current question.
      if (latestDiscovery && view.semantic?.english_question?.text) parts.push(<div key="english" className="step-row"><span>{t('English question for the semantic search')}</span><span className="step-row-text">{view.semantic.english_question.text}</span></div>)
      if (latestDiscovery && view.scope.seeds.length) parts.push(<div key="seeds" className="step-seeds"><span>{t('PDFs guiding the search')}</span>
        {view.scope.seeds.map(seed => row(seed.title, seedUseText(seed.use), seed.source_version_id))}</div>)
      if (run.approval?.approved_by) parts.push(<div key="approved">{approvedByText(run.approval.approved_by)}</div>)
      const attempt = detail(key, state, group)
      if (attempt) parts.push(<div key="attempt">{attempt}</div>)
    }
    if (key === 'search' && run.kind === 'discovery') {
      parts.push(...searchRows())
      if (funnel) parts.push(funnel.chained
        ? <div key="merged">{row(t('Records retrieved by search'), funnel.retrieved.toLocaleString(uiLocale()))}{row(t('Unique works, with the citation chain'), funnel.unique.toLocaleString(uiLocale()))}</div>
        : row(t('Records merged by DOI'), `${funnel.retrieved.toLocaleString(uiLocale())} → ${funnel.unique.toLocaleString(uiLocale())}`, 'merged'))
    }
    if (key === 'chain') {
      parts.push(row(t('Reference lists of {n} seed works', { n: chainSeeds }), plural(chainRecords('backward'), '{n} record returned', '{n} records returned'), 'backward'))
      parts.push(row(t('Works citing the seeds'), plural(chainRecords('forward'), '{n} record returned', '{n} records returned'), 'forward'))
      if (run.source_counts?.counted && run.source_counts.chain) parts.push(row(t('Works the chain brought'), t('{works} works, {only} not found by any search', { works: run.source_counts.chain.works, only: run.source_counts.chain.only }), 'brought'))
      if (chainDone) parts.push(<div key="requests">{chainLine}</div>)
      const limits = run.approval?.chaining
      if (limits) parts.push(<div key="limits">{t('Up to {backward} reference requests and {forward} citing requests · up to {cap} citing works per request · at most {attempts} attempts with retries', { backward: limits.backward_requests, forward: limits.forward_requests, cap: limits.citing_cap, attempts: limits.attempt_limit })}</div>)
    }
    if (key === 'screen' && run.kind === 'discovery') {
      if (readTwice) parts.push(<div key="twice">{t('Each batch is read twice by the literature model. An abstract alone never includes a work.')}</div>)
      if (funnel) {
        const top = t(similarityScored ? 'Ranked by similarity, top {n} read' : 'Top {n} of the ranking read', { n: funnel.abstracts_read.toLocaleString(uiLocale()) })
        parts.push(row(top, notScreened === null ? '' : t('{n} not read', { n: notScreened.toLocaleString(uiLocale()) }), 'top'))
        parts.push(row(t('Passed the abstract stage'), funnel.candidates.toLocaleString(uiLocale()), 'passed'))
      }
    }
    // The works awaiting a person, named once on the run that read them: under its screening, or under its reading when
    // the run reads only.
    if (queueLine && key === (order.includes('screen') ? 'screen' : 'pdf')) parts.push(row(t('Waiting for your decision'), <>{queueLine.count} · <button type="button" className="step-link" onClick={queueLine.open}>{t('Open')}</button></>, 'queue'))
    if (key === 'pdf' && run.kind === 'discovery') {
      if (fetchSummary) parts.push(row(t('Full text retrieved'), fetchSummary.fetched ?? 0, 'fetched'))
      if (group.some(s => s.kind === 'model:fulltext_adjudication' || s.kind === 'code:adjudication_plan')) parts.push(row(t('Full text read (selected pages)'), readingWorks(group).done, 'read'))
      if (fiveCounts) parts.push(row(t('Passed the abstract stage, full text not tried'), <>{fiveCounts.not_read_not_tried}{onOpenPdfs && fiveCounts.not_read_not_tried > 0 && <> · <button type="button" className="step-link" onClick={onOpenPdfs}>{t('Get more full text')}</button></>}</>, 'not-tried'))
      if (fastPath?.K) parts.push(row(t('Full-text limit at {depth} depth', { depth: t(effortLabels[fastPath.mode as keyof typeof effortLabels] ?? fastPath.mode ?? '') }), fastPath.K, 'limit'))
    }
    if (key === 'answer' && run.kind === 'answer' && answer) {
      if (answer.inputs_given) parts.push(row(t('Passages given to the model'), t('{passages} from {sources} sources', { passages: answer.inputs_given.passages, sources: answer.inputs_given.sources }), 'given'))
      if (answer.status === 'structurally_valid') parts.push(row(t('Passages cited'), citedPassages, 'cited'))
      const model = modelRow('Answer model', agents.answer)
      if (model) parts.push(<div key="model">{model}</div>)
      parts.push(<AnswerFlowNote key="flow" answer={answer} />)
    }
    if (key === 'review' && run.kind === 'answer' && !group.length && answer?.status === 'structurally_valid') {
      parts.push(<div key="anchors">{t('Each cited quote was found in a stored passage that was given to this step.')}</div>)
      const review = answer.review
      parts.push(row(review?.model?.resolved_model ? t('Claim review by {model}', { model: review.model.resolved_model }) : t('Claim review'),
        !review ? t('Not recorded for this answer') : review.status !== 'completed' ? t('No usable review') : tally(review.reviews.map(r => r.verdict)).map(([verdict, n]) => `${n} ${t(verdictLabels[verdict as Verdict])}`).join(' · '), 'review'))
    }
    if (note) parts.push(<div key="note" className="chat-step-note">{note}</div>)
    if (seconds !== null && state !== 'running') parts.push(row(t('Time taken'), durationText(seconds), 'time'))
    return parts.length ? <>{parts}</> : null
  }

  // The notice under a stopped run's steps (R18, R21): why it stopped, with Resume run and Cancel run, or for a question
  // too broad to search, a field to rewrite it.
  const resumable = run.status === 'paused' && !(run.pause_reason === 'search_query_failed' && searchQueryTriesLeft(run) === 0)
  const userPaused = run.status === 'paused' && run.pause_reason === 'user_requested'
  const vocabularyEnd = run.status === 'failed' && (run.pause_reason === 'vocabulary_too_broad' || run.pause_reason === 'vocabulary_empty')
  const nextLine = active ? (() => {
    const waiting = [...order.filter((_, i) => phaseStates[i] === 'waiting'), ...(autoAnswer ? ['answer', 'review'] as PhaseKey[] : [])]
      .map(key => t(key === 'pdf' && run.kind !== 'discovery' ? (attachedOnly ? 'read the attached PDFs' : 'download open-access PDFs') : nextNames[key]))
    const at = phaseStates.findIndex(state => state === 'running')
    const stage = stageOffset + (at < 0 ? Math.max(0, phaseStates.findIndex(state => state === 'waiting')) : at) + 1
    return `${t('Next: {list}', { list: waiting.length ? waiting.join(', ') : '—' })} · ${t('stage {n} of {total}', { n: stage, total: stageTotal })}`
  })() : ''
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
        {run.service_wait && <p className="chat-report-line">{serviceWaitRecordText(connectionName(run.service_wait.connection), run.service_wait.attempt, run.service_wait.seconds)}</p>}
        {run.kind === 'answer' && active && run.stage === 'inspection' && steps.some(step => step.kind === 'read_equations' && step.status === 'running') && !steps.some(step => step.kind === 'equations_skip') && <p className="chat-report-line"><button type="button" className="chat-steps-toggle" onClick={() => { api.skipEquations(run.id).catch(() => undefined) }}>{t('Answer now with PDF text')}</button></p>}
        {steps.filter(step => step.kind === 'equations_skipped' && step.status === 'succeeded').map(step => <p key={step.id} className="chat-report-line">{t('Answered now with PDF text; equations of {skipped} PDFs were not read ({read} were read).', { skipped: step.output?.pdfs_skipped ?? 0, read: step.output?.pdfs_read ?? 0 })}</p>)}
        {busyEquationPdfs > 0 && <p className="chat-report-line">{t(busyEquationPdfs === 1 ? 'PDF busy; equations of {n} PDF were not read in this run.' : 'PDF busy; equations of {n} PDFs were not read in this run.', { n: busyEquationPdfs })}</p>}
        {(run.kind === 'review' || (latest && active && !collapsed)) && <div className="chat-run-plan" role="note">
          <Sparkles size={14} strokeWidth={1.8} aria-hidden />
          <div><p className="chat-run-plan-title">{run.kind === 'review' ? (ownerReview && run.target?.plan?.groups ? plural(run.target.plan.groups.length, 'A model you chose reads a stored copy of the {target} in {n} group. It changes nothing in the {target}.', 'A model you chose reads a stored copy of the {target} in {n} groups. It changes nothing in the {target}.', { target: t(ownerReview.kind === 'candidate' ? 'candidate' : ownerReview.kind === 'answer' ? 'answer' : 'report'), n: run.target.plan.groups.length }) : t('A model you chose reads a stored copy. It changes no target text.')) : run.kind === 'report' ? t('Write a sectioned report from the evidence table, one model step per section.') : run.kind === 'discovery' ? t('Search {providers}, then screen the candidates.', { providers }) : run.kind === 'pdf_collection' ? t('Try each included source’s open PDF links, then look once for another open copy.') : run.kind === 'fulltext_fetch' ? t('Retrieve the open full text of the candidate works in rank order; nothing is included or excluded by this.') : run.kind === 'fulltext_adjudication' ? t('A model reads selected passages of each work twice; code checks every quote on the page and decides.') : run.kind === 'pdf_ocr' ? t('Read the pages without text of “{title}” with Tesseract on this computer, one page at a time. No file leaves this computer.', { title: ocrSource?.title ?? t('a PDF') }) : t(attachedOnly ? 'Read the attached PDFs, then write a source-linked answer.' : 'Download the open-access PDFs of the included sources, then write a source-linked answer.')}</p></div>
        </div>}
        <ol className="chat-steps steps">{order.map((key, i) => {
          const state = phaseStates[i]
          // A phase the run has not reached is named in the "Next:" line; a phase it skipped is not drawn.
          if (state === 'waiting' || state === 'skipped') return null
          const group = groups[i]
          const seconds = phaseSeconds(group, state)
          // A live phase is one line; its details open once it has finished. A review run lists its groups as they go.
          const expandable = state !== 'running' || run.kind === 'review'
          const details = expandable ? stepDetail(key, state, group, seconds) : null
          const detailsOpen = Boolean(details) && (openPhases[key] ?? run.kind === 'review')
          const Icon = phaseIcons[key]
          // A search that did not complete belongs to the search line itself, in the attention colour, not to a paragraph after the run (D18).
          const missed = key === 'search' ? failedProviders : []
          return <li key={key} className={`chat-step step is-${state}${detailsOpen ? ' open' : ''}${state === 'attention' ? ' att' : ''}`}>
            <button type="button" className="chat-step-line" disabled={!details} aria-expanded={details ? detailsOpen : undefined}
              onClick={() => setOpenPhases(phases => ({ ...phases, [key]: !detailsOpen }))}>
              <span className="chat-step-icon ico" role="img" aria-label={t(state === 'done' ? 'Done' : state === 'running' ? 'In progress' : 'Stopped here')}>
                {state === 'running' ? <span className="step-spin base" /> : state === 'attention' ? <TriangleAlert size={16} className="base" /> : <Icon size={16} className="base" />}
                {details && <ChevronRight size={16} className="chev" />}
              </span>
              <span className="chat-step-text"><span className={state === 'running' ? 'shimmer-text' : undefined}>{lineText(key, state, group)}</span>
                {missed.length > 0 && <> · <em className="chat-step-missed">{missed.map(([id]) => <ConnectionIcon key={id} id={id} />)}{missed.map(([id, name]) => {
                  const failure = searches.filter(row => row.provider === id && !['completed', 'zero_results'].includes(row.status)).at(-1)
                  return serviceErrorSentence({ kind: serviceKind(failure?.error?.service_kind ?? failure?.error?.error_kind ?? failure?.status, failure?.error?.http_status),
                    service: name, resetAt: failure?.error?.reset_at, effect: run.status === 'completed' ? 'continued' : undefined })
                }).join(' ')}</em></>}</span>
            </button>
            {detailsOpen && <div className="chat-step-detail step-detail">{details}</div>}
          </li>
        })}
        {nextLine && <li className="chat-steps-next next">{nextLine}</li>}
        {/* Which model ran each model phase, and what the run spent behind one quiet toggle (mockup `.usage-line`). */}
        {(run.status !== 'queued' || run.kind === 'review') && run.kind !== 'pdf_collection' && run.kind !== 'pdf_ocr' && run.kind !== 'fulltext_fetch' && <li className="chat-run-meta usage-line">
          {models.length > 0 && <span className="chat-run-models">{models}</span>}
          <button type="button" className="chat-usage-toggle" aria-expanded={usageOpen} onClick={() => setUsageOpen(!usageOpen)}>{t('Usage')}</button>
        </li>}
        {usageOpen && <li className="usage-box">{spend}</li>}
        </ol>
        {(callLimitReached || (retrying && onRetryFailedSearches)) && <div className="chat-run-foot">
          {callLimitReached && <p className="chat-run-limit"><TriangleAlert size={13} aria-hidden />{t('The model call limit for this run was reached.')}</p>}
          {retrying && onRetryFailedSearches && <Button variant="outline" size="sm" onClick={() => void onRetryFailedSearches(run)}>
            <RotateCw size={13} />{t('Retry failed searches')}
          </Button>}
        </div>}
      </>}
    </div>

    {run.status === 'paused' && <div className={`chat-note notice ${userPaused ? 'is-warning' : 'is-error'}`}>
      {userPaused ? <Pause size={16} aria-hidden /> : <TriangleAlert size={16} aria-hidden />}
      <div className="notice-body">
        {userPaused
          ? <p><b>{t('Paused after the current call.')}</b> {t('Nothing was lost: the finished steps are kept and will not run again.')}</p>
          : <p><b>{pauseReasonText(run.pause_reason, run.error)}</b></p>}
        {pauseDetailText(run).map(line => <p key={line}>{line}</p>)}
        {run.kind === 'pdf_ocr' && failedOcrPages.length > 0 && <p>{t('Pages not read: {pages}', { pages: failedOcrPages.join(', ') })}</p>}
        {unknownSteps.length > 0 && <p>{t('Unfinished: {steps}. Resuming repeats it; a repeated model call counts against your account usage.', { steps: unknownSteps.map(s => s.kind === 'model:report_review' ? t('Report review') : stepLabel(s.kind, s.operation_key)).join(', ') })}</p>}
        {run.pause_reason === 'search_query_failed' && searchQueryTriesLeft(run) === 0 && <p>{t('The model has had its second try.')}</p>}
        <div className="notice-actions">
          {resumable && onControlRun && <Button size="sm" disabled={busy} onClick={() => onControlRun(run, 'resume')}><Play size={14} aria-hidden />{t('Resume run')}</Button>}
          {/* Code does not translate a question, so this stop is answered in the revision form and nowhere else (SW2.1). */}
          {run.pause_reason === 'key_terms_needed' && onGiveKeyTerms && <Button variant="outline" size="sm" onClick={onGiveKeyTerms}>{t('Give the English key terms')}</Button>}
          {/* Resume asks the model once more while a try is left; this button never asks it again (D92). */}
          {run.pause_reason === 'search_query_failed' && onChooseCodeQuery && <Button variant="outline" size="sm" onClick={() => void onChooseCodeQuery(run)}>{t('Search with the query built from the question’s words')}</Button>}
          {onControlRun && <Button variant="outline" size="sm" disabled={busy} onClick={() => onControlRun(run, 'cancel')}>{t('Cancel run')}</Button>}
        </div>
      </div>
    </div>}
    {(run.status === 'failed' || run.status === 'cancelled') && run.pause_reason && <div className={`chat-note notice ${vocabularyEnd ? 'is-warning' : run.status === 'failed' ? 'is-error' : 'is-neutral'}`}>
      <TriangleAlert size={16} aria-hidden />
      <div className="notice-body">
        <p>{vocabularyEnd ? pauseReasonText(run.pause_reason, run.error) : <b>{pauseReasonText(run.pause_reason, run.error)}</b>}</p>
        {pauseDetailText(run).map(line => <p key={line}>{line}</p>)}
        {vocabularyEnd && !olderRevision && onRewrite && <RewriteField question={view.scope.question} busy={busy} onRewrite={onRewrite} />}
      </div>
    </div>}
    {children}
    {!children && answer && run.kind === 'answer' && <div className="answer-history-note"><span className="answer-history-icon" aria-hidden="true"><TriangleAlert size={14} /></span><span>{t('An earlier answer: {status}.', { status: t(answer.status.replaceAll('_', ' ')) })}</span></div>}
  </section>
}

// The way on from a question whose words cannot be searched (R21): a field holding the question to rewrite, and Search
// again, which saves the rewritten question as a new revision and searches it. Editing the plan itself waits for the
// Search plan panel (S23b).
function RewriteField({ question, busy, onRewrite }: { question: string; busy: boolean; onRewrite: (question: string) => Promise<void> }) {
  const [draft, setDraft] = useState(question)
  return <>
    <textarea className="notice-field" rows={3} aria-label={t('Rewrite the question')} value={draft} onChange={e => setDraft(e.target.value)} />
    <div className="notice-actions">
      <Button size="sm" disabled={busy || !draft.trim() || draft.trim() === question.trim()} onClick={() => void onRewrite(draft.trim())}><Search size={14} aria-hidden />{t('Search again')}</Button>
    </div>
  </>
}

// The phases of a discovery run, as its run turn lists them; an answer of the fast path counts on from them (R16).
function discoveryOrder(run: Run): PhaseKey[] {
  const steps = run.steps ?? []
  const overlap = (run.budget.fulltext_fetch as unknown as { mode?: string } | undefined)?.mode === 'overlap'
  const chaining = Boolean(run.approval?.chaining?.enabled) || steps.some(s => phaseOf(s.kind) === 'chain')
  return ['plan', 'search', ...(chaining ? ['chain' as const] : []), 'screen', ...(overlap ? ['pdf' as const] : [])]
}
