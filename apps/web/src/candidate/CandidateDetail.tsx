import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, ApiError, type CandidateCard, type CandidateHit, type CandidateMatrix, type CandidatePlan, type CandidateRunRef, type ResearchView } from '../api'
import { ConfirmDialog } from '../ConfirmDialog'
import { ConnectionIcon } from '../connectionIcons'
import { ModelName } from '../ModelName'
import { Notice } from '../Notice'
import { providerName } from '../labels'
import type { ModelText } from '../modelText'
import { t } from '../i18n'
import { CandidateEditor } from './CandidateEditor'
import { ACTIVE, CANDIDATE_KINDS, CandidateRunLine } from './CandidateRunLine'
import { EvidenceSheet } from './EvidenceSheet'
import { SearchMatrix } from './SearchMatrix'
import { StatusDecision } from './StatusDecision'
import { VersionBody } from './VersionBody'
import { dateText, errorText, kindLabels, label, outcomeLabels, refusalLabels } from './labels'
import { useReturnFocus } from './focus'

export function CandidateDetail({ researchId, candidateId, initialCard, view, dark, modelText, onBack, onCard, onRefreshList, onRunChanged }: {
  researchId: string; candidateId: string; initialCard?: CandidateCard; view: ResearchView; dark: boolean; modelText: ModelText
  onBack: () => void; onCard: (card: CandidateCard) => void; onRefreshList: () => Promise<void>; onRunChanged: () => void
}) {
  const [card, setCard] = useState<CandidateCard | null>(initialCard ?? null)
  const [matrix, setMatrix] = useState<CandidateMatrix | null>(null)
  const [selectedSearch, setSelectedSearch] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [matrixError, setMatrixError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState(false)
  const [saved, setSaved] = useState('')
  const [planOpen, setPlanOpen] = useState(false)
  const [plan, setPlan] = useState<CandidatePlan | null>(null)
  const [planError, setPlanError] = useState('')
  const [cancelling, setCancelling] = useState<CandidateRunRef | null>(null)
  const [evidence, setEvidence] = useState<CandidateHit | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const focused = useRef(false)
  const root = useRef<HTMLDivElement>(null)
  const editorControl = useRef<HTMLButtonElement>(null)
  const planControl = useRef<HTMLButtonElement>(null)
  const planHeading = useRef<HTMLHeadingElement>(null)
  const sheetFocus = useReturnFocus()
  const planFocus = useReturnFocus()
  const runFocus = useReturnFocus()
  const generation = useRef(0), applied = useRef(0), planGeneration = useRef(0)
  const closeEditor = () => { setEditor(false); sheetFocus.restoreFocus() }
  const closeEvidence = () => { setEvidence(null); sheetFocus.restoreFocus() }
  const closePlan = () => { planGeneration.current++; setPlanOpen(false); planFocus.restoreFocus() }
  useEffect(() => { if (planOpen) planHeading.current?.focus() }, [planOpen])
  const current = useRef<CandidateCard | null>(initialCard ?? null)
  const pendingRead = useRef<Promise<CandidateCard> | null>(null)
  const onCardRef = useRef(onCard)
  useEffect(() => { onCardRef.current = onCard }, [onCard])
  useEffect(() => { if (card && !focused.current) { heading.current?.focus(); focused.current = true } }, [card])
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
  if (!card) return <div className="candidate-detail"><Button variant="ghost" onClick={onBack}>{t('Candidates')}</Button>{error ? <Notice tone="error">{error}<Button variant="ghost" onClick={() => void load().catch(() => {})}>{t('Retry')}</Button></Notice> : <p role="status">{t('Loading candidate…')}</p>}</div>
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
  const startReason = paused ? t('A run of this candidate is paused: resume or cancel it first') : active ? t(runs.some(r => r.kind === 'kill_search' && ACTIVE.has(r.status)) ? 'Search running' : 'A run is working on this research') : busy ? t('An operation is in progress.') : card.trashed_at ? t('In the Trash') : ''
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
  return <div ref={root} className="candidate-detail">
    <div className="candidate-actions"><Button variant="ghost" onClick={onBack}>{t('Candidates')}</Button><Button variant="ghost" onClick={() => { void onRefreshList(); void load().catch(() => {}); if (planOpen) void loadPlan() }}>{t('Refresh')}</Button></div>
    <div className="candidate-head"><h2 ref={heading} tabIndex={-1}>{t('Candidate card')}</h2>
      <p>{card.origin === 'owner_text' ? t('Your proposal') : t('Opened from a report row: {kind}', { kind: label(kindLabels, card.gap_kind ?? '') })}</p><p className="candidate-claim" data-stored-text>{card.origin_text}</p>
      {card.origin === 'owner_text' && <Notice tone="info">{t('This is your sentence, not a finding from the literature. The breakdown below and the search do not make it one.')}</Notice>}
      {card.origin_changed && <Notice tone="attention">{t('A later candidate was opened from the same report row; the row may have been rewritten. This card keeps the wording it was opened with.')}</Notice>}
      {card.origin === 'report_gap' && <details><summary>{t('What it was opened from')}</summary>{(['basis_cell_ids', 'basis_passage_ids', 'basis_claim_keys'] as const).map(key => <section key={key}><h3>{t({ basis_cell_ids: 'Cell values', basis_passage_ids: 'Passage texts', basis_claim_keys: 'Claim texts' }[key])}</h3>{card.origin_basis_view[key]?.length ? <ul>{card.origin_basis_view[key]!.map(item => <li key={item.id}>{'missing' in item ? t('no longer available') : <span data-stored-text>{item.text}</span>}</li>)}</ul> : <p>{t('None.')}</p>}</section>)}</details>}
    </div>
    {card.trashed_at ? <p>{t('In the Trash')}</p> : <>
      {error && <Notice tone="error">{error}<Button variant="ghost" onClick={() => void load().catch(() => {})}>{t('Retry')}</Button></Notice>}
      {saved && <p role="status">{saved}</p>}
      {!version ? <section className="candidate-section"><h3>{t('No card yet')}</h3><p>{t('at most {n} model calls, no provider requests', { n: card.decompose_budget.max_model_calls })} · <ModelName connection={view.scope.model_connection} text={model} /></p>
        <div className="candidate-actions"><Button disabled={Boolean(startReason)} aria-describedby={startReason ? 'candidate-start-reason' : undefined} onClick={async () => { setBusy(true); setError(''); try { await api.decomposeCandidate(researchId, card.id); onRunChanged(); await load() } catch (e) { setError(errorText(e)) } finally { setBusy(false) } }}>{t('Break the claim into testable parts')}</Button>
          <Button ref={editorControl} variant="outline" onClick={e => openEditor(e.currentTarget)}>{t('Write the card myself')}</Button></div>
      </section> : <><VersionBody version={version} searches={card.searches.filter(s => s.candidate_version_id === version.id).length} /><Button ref={editorControl} variant="outline" onClick={e => openEditor(e.currentTarget)}>{t('Edit card')}</Button>
        <details className="candidate-section"><summary>{t('Earlier versions ({n})', { n: card.versions.length - 1 })}</summary>{card.versions.filter(v => v.id !== card.current_version_id).map(v => <VersionBody key={v.id} version={v} searches={card.searches.filter(s => s.candidate_version_id === v.id).length} />)}</details>
        <section className="candidate-section"><h3>{t('Search for prior art on this claim')}</h3><Button ref={planControl} disabled={Boolean(startReason)} focusableWhenDisabled aria-expanded={planOpen} aria-describedby={startReason ? 'candidate-start-reason' : undefined} onClick={e => { planFocus.rememberFocus(e.currentTarget, () => planControl.current); setPlanOpen(true); setPlan(null); setPlanError(''); void loadPlan() }}>{t('Plan the search')}</Button>
          {planOpen && <section className="candidate-plan" aria-label={t('Search plan')} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); closePlan() } }}><h4 ref={planHeading} tabIndex={-1}>{t('Search plan')}</h4>{planError && <Notice tone="error">{planError}<Button variant="ghost" onClick={() => void loadPlan()}>{t('Retry')}</Button></Notice>}{!plan && !planError && <p role="status">{t('Loading the plan…')}</p>}
            {plan && <><p>{t('Version {n} only; results of other versions are not carried over.', { n: plan.version })}</p><h4>{t('Providers')}</h4><ul>{plan.providers.map(provider => <li key={provider}><ConnectionIcon id={provider} />{providerName(provider)} · {(n => t(n === 1 ? '{n} request per search' : '{n} requests per search', { n }))(plan.transport.providers.find(p => p.provider === provider)?.requests_per_search ?? 0)}</li>)}</ul>
              <h4>{t('Models')}</h4><ul>{(['kill_search_query', 'claim_assessment'] as const).map(task => <li key={task}>{t(task === 'kill_search_query' ? 'Search terms (model)' : 'Claim assessment (model)')} · <ModelName connection={plan.model[task][0]} text={modelText(plan.model[task][1], plan.model[task][2])} /></li>)}</ul>
              <p>{t('At most {queries} queries of {records} records each, no paging.', { queries: plan.limits.queries, records: plan.limits.records })}</p><p>{t('At most {n} works are read.', { n: plan.limits.keep })}</p><p>{t('Reading is title, abstract and stored passages only, never full text.')}</p>
              <p>{t('Model-call ceiling: at most {n} model calls', { n: plan.budget.max_model_calls })}</p><p>{t('Provider-request ceiling: at most {n} provider requests', { n: plan.budget.max_provider_requests })}</p></>}
            <div className="candidate-actions"><Button disabled={!plan || Boolean(startReason)} aria-describedby={startReason ? 'candidate-start-reason' : !plan ? 'candidate-plan-unavailable' : undefined} onClick={() => void start()}>{t('Start')}</Button><Button variant="outline" onClick={closePlan}>{t('Cancel')}</Button></div>{!plan && <p id="candidate-plan-unavailable">{t('A search plan is required before starting.')}</p>}
          </section>}
        </section></>}
      {startReason && <p id="candidate-start-reason">{startReason}</p>}{busy && <p id="candidate-working" role="status">{t('An operation is in progress.')}</p>}
      <section className="candidate-section"><h3>{t('Candidate runs')}</h3><p>{t('The research view contains its newest 10 runs; this card contains its newest 5. These are bounded views, not a complete history.')}</p>{card.runs.length === 5 && <p>{t('Showing the last 5 runs')}</p>}
        {runs.length ? runs.map(run => <CandidateRunLine key={run.id} run={run} fullRun={researchRuns.find(r => r.id === run.id)} matrix={visibleMatrix?.search.run_id === run.id ? visibleMatrix : null} busy={busy} model={model} modelText={modelText} connection={view.scope.model_connection} onControl={(r, action, opener) => void control(r, action, opener)} />) : <p>{t('None.')}</p>}
      </section>
      {card.searches.length > 0 && <section className="candidate-section"><h3>{t('Searches')}</h3><ul>{[...card.searches].sort((a, b) => b.created_at.localeCompare(a.created_at)).map(search => <li key={search.id}><Button variant="ghost" aria-pressed={chosenKid === search.id} onClick={() => { if (chosenKid === search.id) return; setEvidence(null); setMatrix(null); setSelectedSearch(search.id) }}>{t(search.version === card.current_version ? 'Version {n}' : 'Version {n}, not the current version', { n: search.version })} · {dateText(search.created_at)} · {label(outcomeLabels, search.outcome)} · {t('found {found}, kept {kept}', search.counts)}</Button></li>)}</ul></section>}
      {computed && <StatusDecision key={card.current_version_id} card={card} computed={computed} computedVersion={visibleMatrix?.version ?? card.current_version} previous={previous} beginMutation={beginMutation} onChanged={applyMutation} />}
      {matrixError && <Notice tone="error">{matrixError}<Button variant="ghost" onClick={() => void load().catch(() => {})}>{t('Retry')}</Button></Notice>}{chosenKid && !visibleMatrix && !matrixError && <p role="status">{t('Loading matrix…')}</p>}
      {visibleMatrix && <SearchMatrix card={card} matrix={visibleMatrix} onEvidence={(hit, control) => {
        const key = control.dataset.candidateFocus!
        sheetFocus.rememberFocus(control, () => root.current?.querySelector<HTMLElement>(`[data-candidate-focus="${CSS.escape(key)}"]`) ?? null)
        setEvidence(hit)
      }} />}
    </>}
    {editor && <CandidateEditor card={card} researchId={researchId} dark={dark} returnFocus={sheetFocus.returnFocus} beginMutation={beginMutation} onReload={load} onSaved={savedCard} onClose={closeEditor} />}
    {evidence && visibleMatrix && <EvidenceSheet researchId={researchId} card={card} matrix={visibleMatrix} hit={visibleMatrix.hits.find(h => h.source_version_id === evidence.source_version_id) ?? evidence} sourceKey={view.sources.find(s => s.source_version_id === evidence.source_version_id)?.source_key} dark={dark} returnFocus={sheetFocus.returnFocus} onClose={closeEvidence} />}
    <ConfirmDialog open={Boolean(cancelling)} dark={dark} title={t('Cancel this run?')} description={t('The run stops. Records already stored are kept. A cancelled run cannot be resumed.')} confirmLabel={t('Cancel run')} cancelLabel={t('Keep running')} busy={busy} onOpenChange={open => { if (!open) { setCancelling(null); runFocus.restoreFocus() } }} onConfirm={async () => { if (!cancelling) return; setBusy(true); try { await api.controlRun(cancelling.id, 'cancel'); setCancelling(null); onRunChanged(); await load() } catch (e) { setError(errorText(e)); setCancelling(null) } finally { setBusy(false); runFocus.restoreFocus() } }} />
  </div>
}
