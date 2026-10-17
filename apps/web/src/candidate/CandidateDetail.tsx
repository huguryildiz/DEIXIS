import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronRight, CircleX, Lightbulb, ListChecks, PenLine, RotateCw, Search, TriangleAlert } from 'lucide-react'
import { api, ApiError, type CandidateCard, type CandidateHit, type CandidateMatrix, type CandidatePlan, type CandidateRunRef, type CandidateVersion, type ResearchView } from '../api'
import { ConfirmDialog } from '../ConfirmDialog'
import { ConnectionIcon } from '../connectionIcons'
import { ModelName } from '../ModelName'
import { providerName } from '../labels'
import type { ModelText } from '../modelText'
import { t } from '../i18n'
import { CandidateEditor } from './CandidateEditor'
import { useReviewSurface } from '../review/useReviewSurface'
import { CandidateReviewEntry, CandidateReviewHost } from './CandidateReviewSheet'
import { ACTIVE, CANDIDATE_KINDS, CandidateRunLine } from './CandidateRunLine'
import { EvidencePanel } from './EvidenceSheet'
import { SearchMatrix } from './SearchMatrix'
import { StatusDecision } from './StatusDecision'
import { VersionBody } from './VersionBody'
import { dateText, errorText, kindLabels, label, outcomeLabels, refusalLabels } from './labels'
import { useReturnFocus } from './focus'
import type { CandidateSelection } from './CandidatesView'
import { scrollBehavior } from '../motion'

const Failure = ({ text, retry }: { text: string; retry: () => void }) => <div className="notice bad" role="alert"><CircleX aria-hidden /><div className="nb"><span>{text}</span><div className="acts"><button type="button" className="ghost" onClick={retry}>{t('Retry')}</button></div></div></div>

// One candidate (mockup `candDetail`, P35), stacked on the Candidates list: the sentence as the person wrote it (or the
// report row it was opened from), the card, the search plan and searches, the computed status beside the person's own
// decision, and the claim matrix of the chosen search. Nothing here is a finding until a search ran, and the status is
// code's reading of the matrix, not a model verdict.
export function CandidateDetail({ researchId, candidateId, initialCard, intent, view, dark, modelText, onCard, onRefreshList, onRunChanged, onOpenSource }: {
  researchId: string; candidateId: string; initialCard?: CandidateCard; intent?: CandidateSelection; view: ResearchView; dark: boolean; modelText: ModelText
  onCard: (card: CandidateCard) => void; onRefreshList: () => Promise<void>; onRunChanged: () => void; onOpenSource?: (sourceVersionId: string) => void
}) {
  const [card, setCard] = useState<CandidateCard | null>(initialCard ?? null)
  const [matrix, setMatrix] = useState<CandidateMatrix | null>(null)
  const [selectedSearch, setSelectedSearch] = useState<string | null>(intent?.search ?? null)
  const [error, setError] = useState('')
  const [matrixError, setMatrixError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState(false)
  const [saved, setSaved] = useState('')
  const [planOpen, setPlanOpen] = useState(false)
  const [plan, setPlan] = useState<CandidatePlan | null>(null)
  const [planError, setPlanError] = useState('')
  const [cancelling, setCancelling] = useState<CandidateRunRef | null>(null)
  // One review surface for the candidate: the version an entry opened it for stays its target (P32/P33).
  const reviewSurface = useReviewSurface()
  const [reviewTarget, setReviewTarget] = useState<CandidateVersion | null>(null)
  const [reviewRevision, setReviewRevision] = useState(0)
  const [evidence, setEvidence] = useState<CandidateHit | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const editorControl = useRef<HTMLButtonElement>(null)
  const planControl = useRef<HTMLButtonElement>(null)
  const planHeading = useRef<HTMLHeadingElement>(null)
  const sheetFocus = useReturnFocus()
  const planFocus = useReturnFocus()
  const runFocus = useReturnFocus()
  const generation = useRef(0), applied = useRef(0), planGeneration = useRef(0)
  const closeEditor = () => { setEditor(false); sheetFocus.restoreFocus() }
  const closePlan = () => { planGeneration.current++; setPlanOpen(false); planFocus.restoreFocus() }
  useEffect(() => { if (planOpen) planHeading.current?.focus() }, [planOpen])
  const current = useRef<CandidateCard | null>(initialCard ?? null)
  const pendingRead = useRef<Promise<CandidateCard> | null>(null)
  const onCardRef = useRef(onCard)
  useEffect(() => { onCardRef.current = onCard }, [onCard])
  const beginMutation = useCallback(() => ++generation.current, [])
  const load = useCallback(() => {
    const request = ++generation.current
    const response: Promise<CandidateCard> = api.candidate(researchId, candidateId).then(async fresh => {
      if (request !== generation.current || request < applied.current) return pendingRead.current && pendingRead.current !== response ? pendingRead.current : current.current ?? fresh
      applied.current = request; current.current = fresh; setCard(fresh); setError('')
      const kid = selectedSearch ?? [...fresh.searches].reverse().find(s => s.candidate_version_id === fresh.current_version_id)?.id
      if (!kid) { setMatrix(null); setMatrixError(''); return fresh }
      try { const next = await api.candidateMatrix(researchId, candidateId, kid); if (request === generation.current) { setMatrix(next); setMatrixError('') } }
      catch (e) { if (request === generation.current) { setMatrix(null); setMatrixError(errorText(e)) } }
      return current.current ?? fresh
    }, e => { if (request === generation.current) setError(errorText(e)); throw e })
    pendingRead.current = response
    return response
  }, [researchId, candidateId, selectedSearch])
  const runStates = view.runs.filter(r => CANDIDATE_KINDS.has(r.kind) && r.target?.candidate_id === candidateId).map(r => `${r.id}:${r.status}`).join(',')
  const invalidate = useCallback(() => { generation.current++ }, [])
  useEffect(() => { void load().catch(() => {}); return invalidate }, [load, invalidate, view.last_event_id, runStates])
  const applyMutation = (fresh: CandidateCard, request: number) => {
    if (request < applied.current) { void load().catch(() => {}); return }
    applied.current = request; current.current = fresh; setCard(fresh); setError(''); onCardRef.current(fresh)
    if (generation.current !== request) void load().catch(() => {})
  }
  async function loadPlan() {
    const request = ++planGeneration.current
    try { const fresh = await api.candidateKillSearchPlan(researchId, candidateId); if (request === planGeneration.current) { setPlan(fresh) } }
    catch (e) { if (request === planGeneration.current) setPlanError(e instanceof ApiError ? label(refusalLabels, e.message) : errorText(e)) }
  }
  async function start() {
    if (!plan || busy || startReason) return
    setBusy(true); setPlanError('')
    try { await api.startCandidateKillSearch(researchId, candidateId, plan.preview_fingerprint); closePlan(); onRunChanged(); await load() }
    catch (e) { setPlanError(errorText(e)); if (e instanceof ApiError && e.status === 409) await loadPlan() }
    finally { setBusy(false) }
  }
  async function control(run: CandidateRunRef, action: 'pause' | 'resume' | 'cancel', opener: HTMLElement) {
    runFocus.rememberFocus(opener, () => {
      const line = root.current?.querySelector<HTMLElement>(`[data-candidate-run="${CSS.escape(run.id)}"]`)
      return line?.querySelector<HTMLElement>(`[data-run-action="${action}"]`)
        ?? line?.querySelector<HTMLElement>(`[data-run-action="${action === 'pause' ? 'resume' : 'pause'}"]`)
        ?? line?.querySelector<HTMLElement>('[data-run-action="cancel"]') ?? line ?? null
    })
    if (action === 'cancel') { setCancelling(run); return }
    setBusy(true)
    try { await api.controlRun(run.id, action); onRunChanged(); await load() }
    catch (e) { setError(errorText(e)) }
    finally { setBusy(false); runFocus.restoreFocus() }
  }
  // What the opener asked to see (D98), done once per selection when its part of the card has loaded.
  const handled = useRef<CandidateSelection | null>(null)
  useEffect(() => {
    if (!intent || handled.current === intent || !card) return
    // The search the opener described is loaded first, so its matrix and evidence are what the focus lands on.
    if (intent.search && selectedSearch !== intent.search && card.searches.some(s => s.id === intent.search)) {
      setEvidence(null); setMatrix(null); setMatrixError(''); setSelectedSearch(intent.search); return
    }
    const latest = [...card.searches].reverse().find(s => s.candidate_version_id === card.current_version_id)
    const chosen = selectedSearch ?? latest?.id
    if (intent.focus === 'edit') { handled.current = intent; if (!card.trashed_at) { sheetFocus.rememberFocus(editorControl.current ?? root.current!, () => editorControl.current); setEditor(true) } return }
    // The intent stays pending until the chosen search's matrix has loaded: a failed load keeps it for the Retry.
    if (chosen && matrix?.kill_search_id !== chosen) return
    handled.current = intent
    if (intent.focus === 'evidence') { const hit = matrix?.hits.find(h => h.source_version_id === intent.evidence); if (hit) setEvidence(hit); return }
    requestAnimationFrame(() => {
      const target = root.current?.querySelector<HTMLElement>({ matrix: '.candidate-matrix-section h4', review: '.candidate-review-open', decision: '.candidate-status .acts > button' }[intent.focus as 'matrix' | 'review' | 'decision'])
      if (!target) return
      target.scrollIntoView({ block: 'start', behavior: scrollBehavior() })
      if (target.tagName === 'H4') target.tabIndex = -1
      target.focus({ preventScroll: true })
    })
  }, [intent, card, matrix, selectedSearch, sheetFocus])
  const refresh = () => { void onRefreshList(); void load().catch(() => {}); if (planOpen) void loadPlan() }
  const refreshButton = <button type="button" className="ib candidate-refresh" aria-label={t('Refresh')} title={t('Refresh')} onClick={refresh}><RotateCw size={15} aria-hidden /></button>
  if (!card) return <div ref={root} className="candidates-view candidate-detail mk pad detail">
    <div className="venue"><span className="spacer" />{refreshButton}</div>
    {error ? <Failure text={error} retry={() => void load().catch(() => {})} /> : <p role="status" className="foot-note">{t('Loading candidate…')}</p>}
  </div>
  const version = card.versions.find(v => v.id === card.current_version_id)
  const researchRuns = view.runs.filter(r => CANDIDATE_KINDS.has(r.kind) && r.target?.candidate_id === card.id)
  const merged = new Map<string, CandidateRunRef>()
  card.searches.filter(s => s.outcome === 'paused').forEach(s => merged.set(s.run_id, { id: s.run_id, kind: 'kill_search', status: 'paused', pause_reason: null, error_code: null }))
  card.runs.forEach(r => merged.set(r.id, r))
  if (card.active_run) merged.set(card.active_run.id, card.active_run)
  researchRuns.forEach(r => merged.set(r.id, { id: r.id, kind: r.kind, status: r.status, pause_reason: r.pause_reason, error_code: merged.get(r.id)?.error_code ?? (r.status === 'failed' ? r.pause_reason : null) }))
  const runs = [...merged.values()]
  const paused = runs.some(r => r.status === 'paused')
  const active = view.runs.some(r => ACTIVE.has(r.status)) || runs.some(r => ACTIVE.has(r.status))
  const liveRuns = runs.some(r => ACTIVE.has(r.status) || r.status === 'paused')
  const searching = runs.some(r => r.kind === 'kill_search' && ACTIVE.has(r.status))
  const breaking = runs.some(r => r.kind === 'claim_decomposition' && ACTIVE.has(r.status))
  const startReason = paused ? t('A run of this candidate is paused: resume or cancel it first') : active ? t(searching ? 'Search running' : 'A run is working on this research') : busy ? t('An operation is in progress.') : card.trashed_at ? t('In the Trash') : ''
  const latestKid = [...card.searches].reverse().find(s => s.candidate_version_id === card.current_version_id)?.id
  const chosenKid = selectedSearch ?? latestKid
  const visibleMatrix = matrix?.kill_search_id === chosenKid ? matrix : null
  const computed = visibleMatrix?.search_status ?? (chosenKid === latestKid ? card.status?.computed : null)
  const previous = (!visibleMatrix && chosenKid === latestKid) || (visibleMatrix?.is_latest_search_of_version && visibleMatrix.candidate_version_id === card.current_version_id) ? card.status?.previous ?? null : null
  const model = modelText(view.scope.requested_model, view.scope.reasoning_effort)
  const openEditor = (opener: HTMLElement) => { sheetFocus.rememberFocus(opener, () => editorControl.current); setEditor(true) }
  const savedCard = (fresh: CandidateCard, request: number) => {
    applyMutation(fresh, request); setMatrix(null); setSelectedSearch(null); planGeneration.current++; setPlanOpen(false)
    setSaved(t('Saved as version {n}. The searches of earlier versions stay with those versions.', { n: fresh.current_version }))
  }
  const searchedThis = card.searches.some(s => s.candidate_version_id === card.current_version_id)
  const searches = [...card.searches].sort((a, b) => b.created_at.localeCompare(a.created_at))
  const evidenceHit = evidence && visibleMatrix ? visibleMatrix.hits.find(h => h.source_version_id === evidence.source_version_id) ?? evidence : null
  const evidenceSource = evidenceHit && view.sources.find(s => s.source_version_id === evidenceHit.source_version_id)
  return <div ref={root} className="candidates-view candidate-detail mk pad detail">
    <div className="dhead">
      <div className="venue"><span>{card.origin === 'owner_text' ? t('Your sentence') : card.origin === 'answer_thread' ? t('Your sentence from an answer') : t('Opened from a report row: {kind}', { kind: label(kindLabels, card.gap_kind ?? '') })}{card.current_version ? <> · {t('Version {n}', { n: card.current_version })}</> : null}</span><span className="spacer" />{refreshButton}</div>
      <div className="sentence" data-stored-text>{card.origin_text}</div>
      {(card.origin === 'owner_text' || card.origin === 'answer_thread') && <p className="foot-note">{t('This is your sentence, not a finding from the literature. The breakdown below and the search do not make it one.')}</p>}
      {card.origin === 'answer_thread' && card.origin_provenance.aspect_text && <p className="foot-note">{t('Written beside a topic answer V{v} did not answer:', { v: card.origin_provenance.report_version ?? '–' })} <span data-stored-text>{card.origin_provenance.aspect_text}</span></p>}
    </div>
    {card.origin_changed && <div className="notice warn"><TriangleAlert aria-hidden /><span>{t('A later candidate was opened from the same report row; the row may have been rewritten. This card keeps the wording it was opened with.')}</span></div>}
    {card.origin === 'report_gap' && <details className="mk-more"><summary><ChevronRight size={14} aria-hidden />{t('What it was opened from')}</summary>{(['basis_cell_ids', 'basis_passage_ids', 'basis_claim_keys'] as const).map(key => <section key={key}><h5>{t({ basis_cell_ids: 'Cell values', basis_passage_ids: 'Passage texts', basis_claim_keys: 'Claim texts' }[key])}</h5>{card.origin_basis_view[key]?.length ? <ul>{card.origin_basis_view[key]!.map(item => <li key={item.id}>{'missing' in item ? t('no longer available') : <span data-stored-text>{item.text}</span>}</li>)}</ul> : <p>{t('None.')}</p>}</section>)}</details>}
    {card.trashed_at ? <p className="foot-note">{t('In the Trash')}</p> : <>
      {error && <Failure text={error} retry={() => void load().catch(() => {})} />}
      {saved && <p role="status" className="foot-note">{saved}</p>}
      <h4 className="sub">{t('Candidate card')}</h4>
      {!version ? <>
        {breaking ? <p className="foot-note"><span className="spin" aria-hidden /> {t('Breaking the claim into testable parts…')}</p>
          : <p className="foot-note">{t('No card yet.')} {t('at most {n} model calls, no provider requests', { n: card.decompose_budget.max_model_calls })} · <ModelName connection={view.scope.model_connection} text={model} /></p>}
        <div className="acts"><button type="button" className="btn-pri" disabled={Boolean(startReason)} aria-describedby={startReason ? 'candidate-start-reason' : undefined} onClick={async () => { setBusy(true); setError(''); try { await api.decomposeCandidate(researchId, card.id); onRunChanged(); await load() } catch (e) { setError(errorText(e)) } finally { setBusy(false) } }}><Lightbulb aria-hidden />{t('Break the claim into testable parts')}</button>
          <button ref={editorControl} type="button" className="ghost" onClick={e => openEditor(e.currentTarget)}><PenLine aria-hidden />{t('Write the card myself')}</button></div>
      </> : <>
        <VersionBody version={version} origin={card.origin_text} searches={card.searches.filter(s => s.candidate_version_id === version.id).length} />
        <div className="acts"><button ref={editorControl} type="button" className="ghost" onClick={e => openEditor(e.currentTarget)}><PenLine aria-hidden />{t('Edit card')}</button></div>
        {card.versions.length > 1 && <details className="mk-more candidate-earlier"><summary><ChevronRight size={14} aria-hidden />{t('Earlier versions ({n})', { n: card.versions.length - 1 })}</summary>{card.versions.filter(v => v.id !== card.current_version_id).map(v => <div key={v.id} className="candidate-earlier-version"><VersionBody version={v} origin={card.origin_text} earlier searches={card.searches.filter(s => s.candidate_version_id === v.id).length} /><CandidateReviewEntry card={card} version={v} view={view} current={false} active={active} surface={reviewSurface} revision={reviewRevision} onTarget={setReviewTarget} /></div>)}</details>}
        <h4 className="sub" ref={planHeading} tabIndex={-1}>{t('Search plan')}</h4>
        {!planOpen ? <div className="acts"><button ref={planControl} type="button" className="ghost" disabled={Boolean(startReason)} aria-expanded={false} aria-describedby={startReason ? 'candidate-start-reason' : undefined} onClick={e => { planFocus.rememberFocus(e.currentTarget, () => planControl.current); setPlanOpen(true); setPlan(null); setPlanError(''); void loadPlan() }}><ListChecks aria-hidden />{t('Plan the search')}</button></div>
          : <section className="candidate-plan" aria-label={t('Search plan')} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePlan() } }}>
            {planError && <Failure text={planError} retry={() => void loadPlan()} />}{!plan && !planError && <p role="status" className="foot-note">{t('Loading the plan…')}</p>}
            {plan && <><dl className="kv2">
              <dt>{t('Providers')}</dt><dd><ul className="candidate-plan-list">{plan.providers.map(provider => <li key={provider}><ConnectionIcon id={provider} />{providerName(provider)} · {(n => t(n === 1 ? '{n} request per search' : '{n} requests per search', { n }))(plan.transport.providers.find(p => p.provider === provider)?.requests_per_search ?? 0)}</li>)}</ul></dd>
              <dt>{t('Models')}</dt><dd><ul className="candidate-plan-list">{(['kill_search_query', 'claim_assessment'] as const).map(task => <li key={task}>{t(task === 'kill_search_query' ? 'Search terms (model)' : 'Claim assessment (model)')} · <ModelName connection={plan.model[task][0]} text={modelText(plan.model[task][1], plan.model[task][2])} /></li>)}</ul></dd>
              <dt>{t('Searches')}</dt><dd>{t('At most {queries} queries of {records} records each, no paging.', { queries: plan.limits.queries, records: plan.limits.records })}</dd>
              <dt>{t('Reading')}</dt><dd>{t('At most {n} works are read.', { n: plan.limits.keep })} {t('Reading is title, abstract and stored passages only, never full text.')}</dd>
              <dt>{t('Ceilings')}</dt><dd>{t('Model-call ceiling: at most {n} model calls', { n: plan.budget.max_model_calls })} · {t('Provider-request ceiling: at most {n} provider requests', { n: plan.budget.max_provider_requests })}</dd>
            </dl><p className="foot-note">{t('Version {n} only; results of other versions are not carried over.', { n: plan.version })}</p></>}
            <div className="acts"><button type="button" className={searchedThis ? 'ghost' : 'btn-pri'} disabled={!plan || Boolean(startReason)} aria-describedby={startReason ? 'candidate-start-reason' : !plan ? 'candidate-plan-unavailable' : undefined} onClick={() => void start()}><Search aria-hidden />{t(searchedThis ? 'Search again' : 'Search for prior art on this claim')}</button><button type="button" className="ghost" onClick={closePlan}>{t('Cancel')}</button></div>
            {!plan && <p id="candidate-plan-unavailable" className="foot-note">{t('A search plan is required before starting.')}</p>}
          </section>}
        {searches.length > 0 && <section className="candidate-searches" aria-labelledby={`candidate-searches-${card.id}`}><h5 id={`candidate-searches-${card.id}`}>{t('Searches ({n})', { n: searches.length })}</h5><ul className="elist">{searches.map(search => <li key={search.id}><b aria-hidden>{chosenKid === search.id ? '●' : ''}</b><span><button type="button" className="link" aria-pressed={chosenKid === search.id} onClick={() => { if (chosenKid === search.id) return; setEvidence(null); setMatrix(null); setMatrixError(''); setSelectedSearch(search.id) }}>{t(search.version === card.current_version ? 'Version {n}' : 'Version {n}, not the current version', { n: search.version })} · {dateText(search.created_at)} · {label(outcomeLabels, search.outcome)} · {t('found {found}, kept {kept}', search.counts)}</button>{chosenKid === search.id && <small>{t('Shown below')}</small>}</span></li>)}</ul></section>}
      </>}
      {version && !computed && <div className="acts candidate-review-acts"><CandidateReviewEntry card={card} version={version} view={view} current active={active} surface={reviewSurface} revision={reviewRevision} onTarget={setReviewTarget} /></div>}
      {startReason && <p id="candidate-start-reason" className="foot-note">{startReason}</p>}{busy && <p id="candidate-working" role="status" className="foot-note">{t('An operation is in progress.')}</p>}
      {searching && <div className="notice info"><span className="spin" aria-hidden /><span>{t('Searching, then assessing the kept works against the card…')}</span></div>}
      {computed && <StatusDecision key={card.current_version_id} card={card} computed={computed} computedVersion={visibleMatrix?.version ?? card.current_version} previous={previous} beginMutation={beginMutation} onChanged={applyMutation}
        actions={version && <CandidateReviewEntry card={card} version={version} view={view} current active={active} surface={reviewSurface} revision={reviewRevision} onTarget={setReviewTarget} />} />}
      {matrixError && <Failure text={matrixError} retry={() => void load().catch(() => {})} />}{chosenKid && !visibleMatrix && !matrixError && <p role="status" className="foot-note">{t('Loading matrix…')}</p>}
      {visibleMatrix && <SearchMatrix card={card} matrix={visibleMatrix} onEvidence={(hit, control) => {
        const key = control.dataset.candidateFocus!
        sheetFocus.rememberFocus(control, () => root.current?.querySelector<HTMLElement>(`[data-candidate-focus="${CSS.escape(key)}"]`) ?? null)
        setEvidence(hit)
      }} />}
      <details key={liveRuns ? 'live' : 'idle'} open={liveRuns} className="mk-more candidate-runs"><summary><ChevronRight size={14} aria-hidden />{t('Candidate runs')} · {runs.length}</summary>
        <p className="foot-note">{t('The research view contains its newest 10 runs; this card contains its newest 5. These are bounded views, not a complete history.')}{card.runs.length === 5 && <> {t('Showing the last 5 runs')}</>}</p>
        {runs.length ? runs.map(run => <CandidateRunLine key={run.id} run={run} fullRun={researchRuns.find(r => r.id === run.id)} matrix={visibleMatrix?.search.run_id === run.id ? visibleMatrix : null} busy={busy} model={model} modelText={modelText} connection={view.scope.model_connection} onControl={(r, action, opener) => void control(r, action, opener)} />) : <p className="foot-note">{t('None.')}</p>}
      </details>
    </>}
    {(reviewTarget ?? version) && <CandidateReviewHost card={card} version={(reviewTarget ?? version)!} view={view} dark={dark} active={active} surface={reviewSurface} changed={() => { setReviewRevision(n => n + 1); onRunChanged() }} />}
    {editor && <CandidateEditor card={card} researchId={researchId} dark={dark} returnFocus={sheetFocus.returnFocus} beginMutation={beginMutation} onReload={load} onSaved={savedCard} onClose={closeEditor} />}
    {evidenceHit && visibleMatrix && <EvidencePanel researchId={researchId} card={card} matrix={visibleMatrix} hit={evidenceHit} sourceKey={evidenceSource?.source_key} dark={dark}
      onOpenSource={evidenceSource && onOpenSource ? () => onOpenSource(evidenceSource.source_version_id) : undefined} onClose={() => setEvidence(null)} />}
    <ConfirmDialog open={Boolean(cancelling)} dark={dark} title={t('Cancel this run?')} description={t('The run stops. Records already stored are kept. A cancelled run cannot be resumed.')} confirmLabel={t('Cancel run')} cancelLabel={t('Keep running')} busy={busy} onOpenChange={open => { if (!open) { setCancelling(null); runFocus.restoreFocus() } }} onConfirm={async () => { if (!cancelling) return; setBusy(true); try { await api.controlRun(cancelling.id, 'cancel'); setCancelling(null); onRunChanged(); await load() } catch (e) { setError(errorText(e)); setCancelling(null) } finally { setBusy(false); runFocus.restoreFocus() } }} />
  </div>
}
