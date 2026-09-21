import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, Check, ChevronDown, ChevronRight, LoaderCircle, Minus, RotateCw, Sparkles, TriangleAlert } from 'lucide-react'
import type { ResearchView, Run, Verdict } from './api'
import { ocrLanguagesText as ocrLanguages } from './ocr'
import { connectionName, fetchReasonText, pauseReasonText, providerName, runStatusLabels, stepLabel, verdictLabels } from './labels'
import { ConnectionIcon } from './connectionIcons'
import { ProtocolApproval } from './ProtocolApproval'
import { ModelName } from './ModelName'
import type { ModelText } from './modelText'
import { t, uiLocale } from './i18n'
import { scrollBehavior } from './motion'
import { Button } from '@/components/ui/button'

// The research as a record of work: one node per run on a thin rail, each run one line per phase, details a disclosure deeper.
// The page's event stream refreshes the view; a one-second clock keeps running durations moving between events.
// Pause, resume and cancel sit next to the tabs, so one set of controls serves every tab.

type PhaseKey = 'plan' | 'search' | 'screen' | 'pdf' | 'ocr' | 'semantic' | 'answer' | 'review'
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
}
// Attached PDFs are already on this computer: the same phase reads them rather than downloading anything.
const attachedTitles = (n: number): [string, string, string] => n === 1
  ? ['Reading the attached PDF', 'Read the attached PDF', 'Attached PDF']
  : ['Reading the attached PDFs', 'Read the attached PDFs', 'Attached PDFs']
const discoveryHeadings: Record<string, string> = { active: 'Searching and screening', completed: 'Ran search & screening', paused: 'Search & screening paused', failed: 'Search & screening failed', cancelled: 'Search & screening cancelled' }
const collectionHeadings: Record<string, string> = { active: 'Collecting open-access PDFs', completed: 'Collected open-access PDFs', paused: 'PDF collection paused', failed: 'PDF collection failed', cancelled: 'PDF collection cancelled' }
const fulltextHeadings: Record<string, string> = { active: 'Retrieving the full texts', completed: 'Retrieved the full texts', paused: 'Full-text retrieval paused', failed: 'Full-text retrieval failed', cancelled: 'Full-text retrieval cancelled' }
const ocrHeadings: Record<string, string> = { active: 'Reading a PDF with OCR', completed: 'Read a PDF with OCR', paused: 'OCR reading paused', failed: 'OCR reading failed', cancelled: 'OCR reading cancelled' }
const answerHeadings: Record<string, string> = { active: 'Generating the answer', completed: 'Ran answer generation', paused: 'Answer generation paused', failed: 'Answer generation failed', cancelled: 'Answer generation cancelled' }
// The run's stage names the phase it has reached before that phase records its first step.
const stagePhases: Record<string, PhaseKey> = { screening: 'screen', inspection: 'pdf', answer: 'answer', claim_check: 'review' }
const basisLabels: Record<string, string> = { metadata_only: 'metadata only', title_only: 'title only', title_and_abstract: 'title and abstract' }

function phaseOf(kind: string): PhaseKey | null {
  if (kind === 'model:search_plan') return 'plan'
  // An sw run plans its search in code and asks the user before it searches; those steps are its plan phase, so the
  // phase does not read "waiting" while the run has counted its terms and is waiting for the user.
  if (['code:vocabulary', 'model:vocabulary_labels', 'model:criterion_proposal', 'code:criterion', 'code:protocol_approval',
       'code:term_suggestions', 'model:term_suggestions'].includes(kind)) return 'plan'
  if (kind.startsWith('provider_search')) return 'search'
  if (kind === 'model:screening') return 'screen'
  // An sw run screens abstracts in two steps: code classifies every record, then the model proposes.
  if (kind === 'code:abstract_stage' || kind === 'model:abstract_screening') return 'screen'
  if (kind === 'fetch_pdf' || kind === 'pdf_other_copy') return 'pdf'
  // A full-text retrieval run plans, fetches and totals in code; all three belong to the run's one PDF phase.
  if (kind.startsWith('code:fulltext_')) return 'pdf'
  if (kind.startsWith('ocr_')) return 'ocr'
  if (kind.startsWith('embedding:')) return 'semantic'
  if (kind === 'model:grounded_answer') return 'answer'
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
// An embedding model is stored bare for Gemini and as "connection:model" for the others.
const EMBEDDING_CONNECTIONS = new Set(['openai', 'ollama', 'lm_studio'])
const embeddingOf = (stored: string) => {
  const [head, ...rest] = stored.split(':')
  return EMBEDDING_CONNECTIONS.has(head) ? { connection: head, model: rest.join(':') } : { connection: 'gemini', model: stored }
}
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

export function Transcript({ view, emptyText, latestAnswer, modelText, onRetryFailedSearches, onProtocolApproved, onGiveKeyTerms }: {
  view: ResearchView; emptyText: string; latestAnswer: ReactNode; modelText: ModelText
  onRetryFailedSearches?: (run: Run) => Promise<void>
  // The approval card sends its own correction; this only refreshes the view once the backend has taken it.
  onProtocolApproved?: () => void | Promise<void>
  // The way out of a `key_terms_needed` stop: the revision form below, on its key-terms field.
  onGiveKeyTerms?: () => void
}) {
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
  // The current question opens the timeline as the user's turn.
  return <>
  <div className="chat-question"><p dir="auto">{view.scope.question}</p></div>
  <div className={`chat${runs.length ? '' : ' is-empty'}`}>
    {runs.map((run, i) => <RunTurn key={run.id} run={run} view={view} now={now} latest={i === runs.length - 1} modelText={modelText} onRetryFailedSearches={onRetryFailedSearches} onProtocolApproved={onProtocolApproved} onGiveKeyTerms={onGiveKeyTerms}>
      {view.answers[0]?.run_id === run.id ? latestAnswer : null}
    </RunTurn>)}
    {!runs.length && <div className="chat-say"><Sparkles size={18} strokeWidth={1.6} aria-hidden /><p>{emptyText}</p></div>}
    <div ref={end} className="chat-end" />
    {active && !atEnd && <button type="button" className="chat-jump" onClick={() => end.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'end' })}><ArrowDown size={15} aria-hidden />{t('Jump to latest')}</button>}
  </div>
  </>
}

function RunTurn({ run, view, now, latest, modelText, onRetryFailedSearches, onProtocolApproved, onGiveKeyTerms, children }: {
  run: Run; view: ResearchView; now: number; latest: boolean; modelText: ModelText
  onRetryFailedSearches?: (run: Run) => Promise<void>
  onProtocolApproved?: () => void | Promise<void>; onGiveKeyTerms?: () => void; children: ReactNode
}) {
  const active = ACTIVE.has(run.status)
  const [open, setOpen] = useState<boolean | null>(null)
  // Each phase reads as one line; what it found (plan text, concepts, queries, counts) opens under it on request.
  const [openPhases, setOpenPhases] = useState<Partial<Record<PhaseKey, boolean>>>({})
  // While the run works, the phases it has not reached collapse into one "Next:" line; the full ladder stays one click away.
  const [allSteps, setAllSteps] = useState(false)
  // A finished run folds away once something follows it; the latest search stays open so its queries can be read.
  const expanded = open ?? (run.status !== 'completed' || (latest && run.kind === 'discovery'))
  const clock = active ? Math.max(now, Date.parse(run.updated_at)) : Date.parse(run.updated_at)

  const steps = run.steps ?? []
  const order: PhaseKey[] = run.kind === 'discovery' ? ['plan', 'search', 'screen'] : run.kind === 'pdf_collection' || run.kind === 'fulltext_fetch' ? ['pdf'] : run.kind === 'pdf_ocr' ? ['ocr'] : ['pdf', 'semantic', 'answer', ...(view.reviewer.model ? ['review' as const] : [])]
  const groups = order.map(key => steps.filter(s => phaseOf(s.kind) === key))
  const reached = Math.max(order.indexOf(stagePhases[run.stage]), ...groups.map((group, i) => (group.length ? i : -1)))
  const searches = view.search_runs.filter(s => s.run_id === run.id)
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
  // A pdf_ocr run (D51): its PDF, the pages without text it found, and what became of the merged text.
  const ocrSource = run.kind === 'pdf_ocr' ? view.sources.find(s => s.source_version_id === run.target?.source_version_id) : undefined
  const ocrAsset = ocrSource?.access.assets.find(a => a.id === run.target?.asset_id)
  const ocrPages = steps.find(s => s.kind === 'ocr_pages')?.output?.image_pages
  const rationaleOf = (provider: string, query: string) => plan?.queries.find(q => q.provider_id === provider && q.query_text === query)?.rationale ?? ''

  const stateOf = (i: number): PhaseState => {
    const hasTrouble = groups[i].some(troubled)
    if (groups[i].some(step => step.status === 'running')) return 'running'
    if (i < reached) return hasTrouble ? 'attention' : groups[i].length ? 'done' : 'skipped'
    if (i === reached) return active ? 'running' : hasTrouble ? 'attention' : run.status === 'completed' ? 'done' : 'attention'
    if (active && reached < 0 && i === 0 && run.status !== 'queued') return 'running'
    return active || run.status === 'paused' ? 'waiting' : 'skipped'
  }

  // A research of attached files alone reads PDFs it already has; nothing is downloaded, so the PDF phase says so.
  const attachedOnly = view.scope.source_scope === 'attached'

  const title = (key: PhaseKey, state: PhaseState, group: Step[]) => {
    const finished = searches.filter(s => s.status === 'completed' || s.status === 'zero_results').length
    if ((state === 'done' || state === 'attention') && key === 'search' && finished) return plural(finished, 'Conducted {n} search', 'Conducted {n} searches')
    if (state === 'done' && key === 'pdf') return plural(group.filter(s => s.status === 'succeeded').length, attachedOnly ? 'Read {n} attached PDF' : 'Downloaded {n} open-access PDF', attachedOnly ? 'Read {n} attached PDFs' : 'Downloaded {n} open-access PDFs')
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
        const parts = [state === 'running' && group.length ? plural(ok.length, attachedOnly ? '{n} read' : '{n} downloaded', attachedOnly ? '{n} read' : '{n} downloaded') : '',
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
          merged && last ? plural(last.pages_with_text, '{n} with text', '{n} with text') : '',
          merged && last?.blank_pages ? plural(last.blank_pages, '{n} blank page skipped', '{n} blank pages skipped') : '',
          merged ? (merged.outcome === 'current' ? t('in use') : t('not used: {reason}', { reason: merged.rejection_reason ?? '' })) : '',
          run.target?.languages ? ocrLanguages(run.target.languages) : ''].filter(Boolean).join(' · ')
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
        if (perProvider.size < 2) return null  // a single provider is already named on each query row below
        return <p className="chat-provider-totals">{[...perProvider].map(([id, { taken, total }]) => <span key={id}>
          <ConnectionIcon id={id} />{providerName(id)} {total !== null && total > taken ? t('{count} of {total}', { count: taken, total: compact(total) }) : taken}
        </span>)}</p>
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
        const timed = (step?: Step) => { const s = stepSeconds(step); return s === null ? null : <time>{durationText(s)}</time> }
        // One line per finding, each with the time its step took.
        return <>
          {similarity && similarityModel && <p className="chat-report-line">
            <span>{similarity.status === 'succeeded'
              ? <>{plural(similarity.output?.sources ?? 0, 'Similarity to the question: {n} source scored', 'Similarity to the question: {n} sources scored')}
                <span className="chat-run-model chat-report-model"><ConnectionIcon id={similarityModel.connection} /><span className="sr-only">{connectionName(similarityModel.connection)} · </span>{similarityModel.model}</span></>
              : t('Similarity unavailable; ordered by search position')}</span>
            {timed(similarity)}
          </p>}
          {lines.length > 0 && <p className="chat-report-line"><span>{lines.join(' · ')}</span></p>}
          {run.screening_notes.map(note => <p key={note.step_id} className="chat-report-line"><span>{note.text}</span>{timed(steps.find(s => s.id === note.step_id))}</p>)}
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
  const { connection: embeddingConnection, model: embeddingModel } = embeddingOf(embeddingStoredModel)
  const embeddingProviders: Record<string, string> = { gemini: 'Gemini', openai: 'OpenAI', ollama: 'Ollama', lm_studio: 'LM Studio' }
  const agents: Partial<Record<PhaseKey, { role: string; connection: string; model: string | null; effort: string | null }>> = {
    plan: literature, screen: literature,
    semantic: embeddingStep ? { role: embeddingProviders[embeddingConnection], connection: embeddingConnection, model: embeddingModel, effort: null } : undefined,
    answer: { role: 'Answer', connection: answer?.model?.connection ?? scope.model_connection, model: answer?.model?.resolved_model ?? answer?.model?.requested_model ?? scope.requested_model, effort: scope.reasoning_effort },
    review: { role: 'Reviewer', connection: answer?.review?.model?.connection ?? view.reviewer.connection ?? scope.model_connection, model: answer?.review?.model?.resolved_model ?? view.reviewer.model, effort: view.reviewer.reasoning_effort },
  }
  const providers = new Intl.ListFormat(uiLocale(), { type: 'conjunction' }).format(view.scope.providers.map(providerName))
  // Worded as what happened, so it reads apart from the run strip's status next to the tabs.
  const outcome = active ? 'active' : run.status
  const label = t((run.kind === 'discovery' ? discoveryHeadings : run.kind === 'pdf_collection' ? collectionHeadings : run.kind === 'fulltext_fetch' ? fulltextHeadings : run.kind === 'pdf_ocr' ? ocrHeadings : answerHeadings)[outcome] ?? runStatusLabels[run.status])
  const olderRevision = run.scope_revision !== view.research.current_scope_revision
  const tokens = totalTokens(answer?.model?.token_usage)
  // What the run spent against what it was allowed; the token figure is the answer step's own, and no cost is estimated.
  const spend = [t('Model calls {calls}/{limit}', { calls: run.usage.model_calls ?? 0, limit: run.budget.max_model_calls ?? 0 }),
    t('provider requests {requests}/{limit}', { requests: run.usage.provider_requests ?? 0, limit: run.budget.max_provider_requests ?? 0 }),
    ...(tokens === null ? [] : [t('{n} answer tokens', { n: compact(tokens) })])].join(' · ')
  // Which model ran each model phase of this run, listed once here rather than on every step line.
  const models = order.filter((key, i) => agents[key]?.model && stateOf(i) !== 'skipped').map(key => agents[key]!)
    .filter((agent, i, all) => all.findIndex(a => a.role === agent.role) === i)  // the literature model plans and screens; name it once
    .map(agent => <span key={agent.role} className="chat-run-model">{agent.role && <>{t(agent.role)} · </>}<ModelName connection={agent.connection} text={modelText(agent.model, agent.effort)} /></span>)
  // Live runs read as one line of work: what the run has not reached, and what it skips, stay out until it is done.
  const phaseStates = order.map((_, i) => stateOf(i))
  const idle = (state: PhaseState) => state === 'waiting' || state === 'skipped'
  const collapsed = active && !allSteps && phaseStates.some(idle)
  const waitingNext = collapsed ? order.filter((_, i) => phaseStates[i] === 'waiting').map(key => t((key === 'pdf' && attachedOnly ? attachedTitles(included.length) : titles[key])[2]).toLocaleLowerCase(uiLocale())) : []
  return <section className={`chat-turn${active ? ' is-active' : ''}`}>
    <div className="chat-group">
      <button type="button" className="chat-toggle" aria-expanded={expanded} onClick={() => setOpen(!expanded)}>
        {expanded ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
        <span className={active ? 'shimmer-text' : undefined}>{label}{olderRevision ? ` ${t('· for question revision {n}', { n: run.scope_revision })}` : ''}</span>
        {active && <LoaderCircle size={14} className="chat-spin" aria-hidden />}
        <span className="chat-when">{startedText(started)}</span>
        <time>{durationText(secondsBetween(started, clock))}</time>
      </button>
      {expanded && <>
        {latest && active && !collapsed && <div className="chat-run-plan" role="note">
          <Sparkles size={14} strokeWidth={1.8} aria-hidden />
          <div><p className="chat-run-plan-title">{run.kind === 'discovery' ? t('Search {providers}, then screen the candidates.', { providers }) : run.kind === 'pdf_collection' ? t('Try each included source’s open PDF links, then look once for another open copy.') : run.kind === 'fulltext_fetch' ? t('Retrieve the open full text of the candidate works in rank order; nothing is included or excluded by this.') : run.kind === 'pdf_ocr' ? t('Read the pages without text of “{title}” with Tesseract on this computer, one page at a time. No file leaves this computer.', { title: ocrSource?.title ?? t('a PDF') }) : t(attachedOnly ? 'Read the attached PDFs, then write a source-linked answer.' : 'Download the open-access PDFs of the included sources, then write a source-linked answer.')}</p></div>
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
        const detailsOpen = openPhases[key] ?? (hasQueries && state === 'running')
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
          {collapsed && state === 'running' && <div className="chat-step-progress">
            <span className="chat-step-progress-bar"><span style={{ width: `${Math.round(((i + 0.5) / order.length) * 100)}%` }} /></span>
            <small>{t('step {n} of {total}', { n: i + 1, total: order.length })}</small>
          </div>}
          {note && detailsOpen && <div className="chat-step-note">{note}</div>}
          {hasConcepts && detailsOpen && <ul className="chat-list">
            {plan?.concepts.map(c => <li key={c.label}>
              <span className="chat-list-text"><b>{c.label}</b>{c.synonyms.length ? ` · ${c.synonyms.join(', ')}` : ''}</span>
              <small>{t(c.role.replace('_', ' '))}</small>
            </li>)}
          </ul>}
          {hasQueries && detailsOpen && <ul className="chat-list">
            {searches.map(s => {
              const ok = s.status === 'completed' || s.status === 'zero_results'
              const why = rationaleOf(s.provider, s.query_text)
              return <li key={s.id} className={ok ? undefined : 'is-attention'}>
                <span className="chat-list-text"><code>{s.query_text}</code>{why && <small>{why}</small>}</span>
                <span className="chat-list-meta"><ConnectionIcon id={s.provider} />{providerName(s.provider)} · <b>{ok ? t('{count} / {total}', { count: s.result_count, total: s.provider_total === null ? '?' : compact(s.provider_total) }) : t(s.status.replace('_', ' '))}</b></span>
              </li>
            })}
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
          {run.status !== 'queued' && run.kind !== 'pdf_collection' && run.kind !== 'pdf_ocr' && run.kind !== 'fulltext_fetch' && <p className="chat-run-meta">
            {models.length > 0 && <span className="chat-run-models">{models}</span>}
            <span>{spend}</span>
          </p>}
          {/* Pause, resume and cancel ride with the tabs, where every tab reaches them; the foot only opens the full ladder. */}
          {active && order.length > 1 && <button type="button" className="chat-steps-toggle" onClick={() => setAllSteps(!allSteps)}>{t(allSteps ? 'Show fewer steps' : 'Show every step')}</button>}
          {retrying && onRetryFailedSearches && <Button variant="outline" size="sm" onClick={() => void onRetryFailedSearches(run)}>
            <RotateCw size={13} />{t('Retry failed searches')}
          </Button>}
        </div>
      </>}
    </div>

    {run.status === 'paused' && <div className="chat-note is-warning">
      <p>{pauseReasonText(run.pause_reason)}</p>
      {run.kind === 'pdf_ocr' && failedOcrPages.length > 0 && <p>{t('Pages not read: {pages}', { pages: failedOcrPages.join(', ') })}</p>}
      {unknownSteps.length > 0 && <p>{t('Unfinished: {steps}. Resuming repeats it; a repeated model call counts against your account usage.', { steps: unknownSteps.map(s => stepLabel(s.kind, s.operation_key)).join(', ') })}</p>}
      {/* Code does not translate a question, so this stop is answered in the revision form and nowhere else (SW2.1). */}
      {run.pause_reason === 'key_terms_needed' && onGiveKeyTerms && <Button variant="outline" size="sm" onClick={onGiveKeyTerms}>{t('Give the English key terms')}</Button>}
    </div>}
    {/* What this run would search with, before it searches: the user corrects it here and approves it (D80). */}
    {run.approval && <ProtocolApproval run={run} approval={run.approval} onApproved={() => onProtocolApproved?.()} />}
    {(run.status === 'failed' || run.status === 'cancelled') && run.pause_reason && <div className={`chat-note ${run.status === 'failed' ? 'is-error' : 'is-neutral'}`}><p>{pauseReasonText(run.pause_reason)}</p></div>}
    {children}
    {!children && answer && run.kind === 'answer' && <div className="answer-history-note"><span className="answer-history-icon" aria-hidden="true"><TriangleAlert size={14} /></span><span>{t('An earlier answer: {status}.', { status: t(answer.status.replaceAll('_', ' ')) })}</span></div>}
  </section>
}
