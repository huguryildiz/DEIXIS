import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, FileUp, Pause, Play, Search, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, subscribe, type ActivityEvent, type Answer, type ResearchView, type Run, type Source } from './api'
import { accessText, locatorText, pauseReasonText, runStatusLabels, scopeLabels, stepLabel } from './labels'
import { PassageSheet } from './PassageSheet'

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function ResearchPage({ id, dark, onChanged }: { id: string; dark: boolean; onChanged: () => void }) {
  const [view, setView] = useState<ResearchView | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [tab, setTab] = useState('answer')
  const [passageId, setPassageId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const fileInput = useRef<HTMLInputElement>(null)
  const firstEvent = useRef<number | null>(null)

  const load = useCallback(async () => {
    try { const next = await api.research(id); setView(next); setError(''); if (firstEvent.current === null) firstEvent.current = next.last_event_id } catch (e) { setError(errorText(e)) }
  }, [id])
  useEffect(() => { void load() }, [load])

  const loaded = view !== null
  useEffect(() => {
    if (!loaded) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const stop = subscribe(id, firstEvent.current ?? 0, () => { clearTimeout(timer); timer = setTimeout(() => { void load(); onChanged() }, 250) })
    return () => { stop(); clearTimeout(timer) }
  }, [id, loaded, load, onChanged])

  useEffect(() => {
    if (tab !== 'activity') return
    api.events(id).then(setEvents).catch(e => setNotice(errorText(e)))
  }, [tab, id, view?.last_event_id])

  async function act(action: () => Promise<unknown>, success?: string) {
    setBusy(true)
    setNotice('')
    try { await action(); if (success) setNotice(success); await load(); onChanged() } catch (e) { setNotice(errorText(e)) } finally { setBusy(false) }
  }

  if (error && !view) return <section className="research-view"><div className="legacy-boundary">Could not open this research: {error}</div></section>
  if (!view) return <section className="research-view"><p className="session-meta">Loading research…</p></section>

  const run = view.runs[0] as Run | undefined
  const active = run ? ACTIVE.has(run.status) : false
  const answer = view.answers[0] as Answer | undefined
  const hasAcademic = view.scope.source_scope !== 'attached'
  const included = view.counts.included
  const unknownSteps = run?.steps?.filter(s => s.status === 'outcome_unknown') ?? []

  const startAnswer = () => act(() => api.startRun(id, 'answer', crypto.randomUUID()))
  const startDiscovery = () => act(() => api.startRun(id, 'discovery', crypto.randomUUID()))
  const upload = (list: FileList | null) => list && act(async () => { for (const file of Array.from(list)) await api.upload(id, file) }, 'PDF added and included. Its text was extracted page by page (no OCR).')

  return <section className="research-view legacy-research">
    <div className="section-label">RESEARCH <span> / REVISION {view.research.current_scope_revision}</span></div>
    <h1>{view.scope.question}</h1>
    <p className="session-meta">{scopeLabels[view.scope.source_scope]} · {view.scope.effort} depth · Codex{view.scope.requested_model ? ` · ${view.scope.requested_model}` : ' · default model'}</p>

    <div className="legacy-progress run-card">
      <div className="legacy-progress-head">
        <div>
          <strong>{run ? `${run.kind === 'discovery' ? 'Search & screening' : 'Answer'} · ${runStatusLabels[run.status]}` : 'Nothing has run yet'}</strong>
          <small>{run ? (pauseReasonText(run.pause_reason) || `Stage: ${run.stage}`) : hasAcademic ? 'Start an academic search, or attach PDFs.' : 'Attach PDFs, then generate an answer.'}</small>
        </div>
        <div className="run-actions">
          {run && active && run.status !== 'pause_requested' && <Button variant="outline" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'pause'))}><Pause size={14} />Pause</Button>}
          {run && run.status === 'paused' && <Button variant="outline" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'resume'))}><Play size={14} />Resume</Button>}
          {run && (active || run.status === 'paused') && <Button variant="ghost" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'cancel'))}><X size={14} />Cancel</Button>}
        </div>
      </div>
      {run?.status === 'paused' && unknownSteps.length > 0 && <p className="legacy-mini-note run-warning">Unfinished: {unknownSteps.map(s => stepLabel(s.kind, s.operation_key)).join(', ')}. Resuming repeats it; a repeated model call counts against your account usage.</p>}
      <div className="legacy-counts run-counts">
        {([['found', 'Found'], ['unique', 'Unique records'], ['included', 'Included'], ['inspected', 'Given to the model'], ['cited', 'Cited']] as const).map(([key, label]) => <div key={key}><strong>{view.counts[key]}</strong><span>{label}</span></div>)}
      </div>
      {run?.steps && run.steps.length > 0 && <details><summary>Processing steps <ChevronDown size={14} /></summary><ol>{run.steps.map((step, index) => <li key={step.id}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{stepLabel(step.kind, step.operation_key)}</strong><p>{step.status.replace('_', ' ')}{step.error_code ? ` · ${step.error_code}` : ''}{step.attempt > 1 ? ` · attempt ${step.attempt}` : ''}</p></div><small>{step.finished_at ? new Date(step.finished_at).toLocaleTimeString() : ''}</small></li>)}</ol><p className="legacy-mini-note">Counts use DEIXIS source versions. “Given to the model” counts sources whose passages were sent in the latest answer step; it is not a full-text reading claim.</p></details>}
    </div>

    <Tabs value={tab} onValueChange={value => setTab(String(value))}>
      <TabsList><TabsTrigger value="answer">Answer</TabsTrigger><TabsTrigger value="sources">Sources ({view.sources.length})</TabsTrigger><TabsTrigger value="activity">Activity</TabsTrigger></TabsList>

      <TabsContent value="answer">
        {answer ? <AnswerBlock answer={answer} onOpen={setPassageId} /> : <div className="empty-inline"><p>{included ? `${included} source${included === 1 ? ' is' : 's are'} included. Generate an answer when your selection is ready.` : view.sources.length ? 'Include at least one source on the Sources tab.' : 'No sources yet.'}</p></div>}
        <div className="answer-actions">
          <Button disabled={busy || active || !included} onClick={startAnswer}><Sparkles size={15} />{answer ? 'Generate a new answer' : 'Generate source-linked answer'}</Button>
          {hasAcademic && <Button variant="outline" disabled={busy || active} onClick={startDiscovery}><Search size={15} />{view.search_runs.length ? 'Search again' : 'Search OpenAlex'}</Button>}
        </div>
      </TabsContent>

      <TabsContent value="sources">
        <div className="legacy-section-head"><div><div className="section-label">SELECTION</div><h2>Sources and access</h2><p>Your choice always overrides the model’s screening proposal. Access, retrieval and inspection are separate states.</p></div>
          <Button variant="outline" disabled={busy} onClick={() => fileInput.current?.click()}><FileUp size={14} />Attach PDF</Button></div>
        <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void upload(e.target.files); e.target.value = '' }} />
        {view.search_runs.length > 0 && <div className="search-summary">{view.search_runs.map(s => <div key={s.id}><Search size={13} /><span>“{s.query_text}”</span><small>{s.provider} · {s.status.replace('_', ' ')} · {s.result_count} of {s.provider_total ?? '?'} records · {s.access_mode}</small></div>)}</div>}
        {view.sources.map(source => <SourceRow key={source.source_version_id} source={source} busy={busy}
          onSelect={state => act(() => api.select(id, source.source_version_id, state, source.selection.version))}
          onAbstract={() => source.access.abstract_passage_id && setPassageId(source.access.abstract_passage_id)} />)}
        {!view.sources.length && <p className="empty-inline">No sources yet.</p>}
      </TabsContent>

      <TabsContent value="activity">
        <ol className="activity-list">{events.slice().reverse().map(event => <li key={event.id}><time>{new Date(event.created_at).toLocaleString()}</time><span>{describeEvent(event)}</span></li>)}</ol>
        {!events.length && <p className="empty-inline">No recorded activity.</p>}
      </TabsContent>
    </Tabs>

    <RevisionForm key={view.research.version} question={view.scope.question} disabled={busy || active}
      onSubmit={text => act(() => api.reviseScope(id, text, view.research.version), 'Question revised. Earlier answers stay visible and are marked as belonging to the previous revision.')} />
    {notice && <div role="status" className="notice">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={16} /></button></div>}
    <PassageSheet researchId={id} passageId={passageId} dark={dark} onClose={() => setPassageId(null)} />
  </section>
}

function AnswerBlock({ answer, onOpen }: { answer: Answer; onOpen: (passageId: string) => void }) {
  if (answer.status === 'clarification' && answer.clarification) {
    return <div className="legacy-answer"><div className="section-label">CLARIFICATION NEEDED</div><h2>{answer.clarification.question}</h2><p>{answer.clarification.why_it_matters}</p>{answer.clarification.options.length > 0 && <ul className="plain-list">{answer.clarification.options.map(o => <li key={o}>{o}</li>)}</ul>}<p className="legacy-mini-note">Revise the question below to continue.</p></div>
  }
  if (answer.status === 'no_evidence') {
    return <div className="legacy-boundary">No text passages were available for the included sources (no abstract, no retrievable PDF text). No answer was generated.</div>
  }
  if (answer.status === 'unverified_draft') {
    return <div className="legacy-answer"><div className="legacy-boundary">The model output failed validation after one repair attempt, so it is not shown as a cited answer.<ul className="plain-list">{answer.validation.issues?.map(i => <li key={`${i.code}${i.path}`}>{i.code} at {i.path}</li>)}</ul></div>
      {answer.unverified_draft?.claims?.map(c => <p className="claim is-unverified" key={c.claim_label}>{c.text}</p>)}</div>
  }
  const refs = new Map<string, { n: number; e: Answer['claims'][number]['evidence'][number] }>()
  answer.claims.forEach(c => c.evidence.forEach(e => { if (!refs.has(e.passage_id)) refs.set(e.passage_id, { n: refs.size + 1, e }) }))
  return <div className="legacy-answer">
    <div className="section-label">SOURCE-LINKED ANSWER{answer.applicability === 'stale_scope' ? ' · EARLIER QUESTION REVISION' : ''}</div>
    {answer.applicability === 'stale_scope' && <div className="legacy-boundary">This answer was produced for revision {answer.scope_revision} of the question and is not applied to the current revision.</div>}
    {answer.capability_notice && <div className="legacy-boundary">{answer.capability_notice}</div>}
    {answer.claims.map(claim => <p className="claim" key={claim.id}>
      {claim.text}{claim.support_type === 'analyst_inference' && <span className="support-badge">interpretation</span>}
      {claim.evidence.map(e => <button key={e.passage_id} className="cite-chip" title={`${e.title} · ${locatorText(e)}`} onClick={() => onOpen(e.passage_id)}>[{refs.get(e.passage_id)?.n}]</button>)}
    </p>)}
    {!answer.claims.length && <p>No claim could be linked to the passages given to the model.</p>}
    {answer.unanswered_aspects.length > 0 && <><h3>Not answered by the inspected passages</h3><ul className="plain-list">{answer.unanswered_aspects.map(a => <li key={a}>{a}</li>)}</ul></>}
    {answer.limitations.length > 0 && <><h3>Limits</h3><ul className="plain-list">{answer.limitations.map((l, i) => <li key={i}><em>{l.kind.replace('_', ' ')}:</em> {l.text}</li>)}</ul></>}
    {refs.size > 0 && <><h3>Cited passages</h3><ol className="reference-list">{[...refs.values()].map(({ n, e }) => <li key={e.passage_id}><button onClick={() => onOpen(e.passage_id)}><span>[{n}]</span> {e.title} — {locatorText(e)}{e.reading_depth === 'abstract' ? ' · abstract only' : ''}</button></li>)}</ol></>}
    <p className="legacy-mini-note">Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked. {answer.model ? `Model: ${answer.model.connection} · ${answer.model.resolved_model ?? answer.model.requested_model ?? 'unknown'}.` : ''} {answer.inputs_given ? `${answer.inputs_given.passages} passages from ${answer.inputs_given.sources} sources were provided.` : ''}</p>
  </div>
}

function SourceRow({ source, busy, onSelect, onAbstract }: { source: Source; busy: boolean; onSelect: (state: Source['selection']['state']) => void; onAbstract: () => void }) {
  const s = source.selection
  const meta = [source.authors.slice(0, 3).join(', ') + (source.authors.length > 3 ? ' et al.' : ''), source.year, source.venue, source.version_label].filter(Boolean).join(' · ')
  return <div className={`source-row is-${s.state}`}>
    <div className="source-main">
      <strong>{source.title}</strong>
      <small>{meta || (source.origin === 'user_upload' ? 'Uploaded PDF' : 'No bibliographic details from the provider')}</small>
      <small className="access-line">{accessText(source)}{source.cited_in_latest_answer ? ' · cited in the latest answer' : ''}</small>
      {s.proposal && <p className="proposal">Model proposal: <em>{s.proposal}</em> — {s.proposal_reason} <span>({s.proposal_basis?.replaceAll('_', ' ')})</span>{s.origin === 'user' ? ' · overridden by you' : ''}</p>}
      <div className="source-links">
        {source.access.abstract_passage_id && <button onClick={onAbstract}>Read abstract</button>}
        {source.doi && <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer">DOI</a>}
        {!source.doi && source.landing_url && <a href={source.landing_url} target="_blank" rel="noreferrer">Publisher page</a>}
      </div>
    </div>
    <div className="selection-toggle" role="group" aria-label={`Selection for ${source.title}`}>
      {(['included', 'pending', 'excluded'] as const).map(state => <button key={state} aria-pressed={s.state === state} disabled={busy || s.state === state} onClick={() => onSelect(state)}>{state === 'included' ? 'Include' : state === 'excluded' ? 'Exclude' : 'Undecided'}</button>)}
    </div>
  </div>
}

function RevisionForm({ question, disabled, onSubmit }: { question: string; disabled: boolean; onSubmit: (text: string) => void }) {
  const [text, setText] = useState(question)
  return <form className="legacy-followup" onSubmit={e => { e.preventDefault(); if (text.trim() && text.trim() !== question) onSubmit(text.trim()) }}>
    <label htmlFor="revise-question">Revise the question</label>
    <textarea id="revise-question" value={text} onChange={e => setText(e.target.value)} />
    <div><span>Creates a new question revision. Sources and earlier answers are kept.</span><Button type="submit" disabled={disabled || !text.trim() || text.trim() === question}>Save revision</Button></div>
  </form>
}

function describeEvent(event: ActivityEvent) {
  const p = event.payload as Record<string, string | number | null>
  switch (event.type) {
    case 'research_created': return 'Research created'
    case 'scope_revised': return `Question revised (revision ${p.scope_revision})`
    case 'run_queued': return `${p.kind === 'discovery' ? 'Search' : 'Answer'} run queued`
    case 'run_started': return 'Run started'
    case 'run_completed': return 'Run completed'
    case 'run_paused': return `Run paused${p.pause_reason ? `: ${pauseReasonText(String(p.pause_reason))}` : ''}`
    case 'run_failed': return `Run failed${p.pause_reason ? `: ${pauseReasonText(String(p.pause_reason))}` : ''}`
    case 'run_resumed': return 'Run resumed'
    case 'run_cancelled': return 'Run cancelled'
    case 'run_pause_requested': return 'Pause requested'
    case 'step_started': return `${stepLabel(String(p.kind), String(p.operation_key))} started`
    case 'step_finished': return `${stepLabel(String(p.kind), String(p.operation_key))}: ${String(p.status).replace('_', ' ')}${p.error_code ? ` (${p.error_code})` : ''}`
    case 'model_call_started': return `Model call sent to ${p.connection}${p.requested_model ? ` · ${p.requested_model}` : ''}`
    case 'search_recorded': return `OpenAlex search: ${String(p.status).replace('_', ' ')}, ${p.result_count} records`
    case 'selection_changed': return `You marked a source as ${p.state}`
    case 'answer_saved': return `Answer saved (${String(p.status).replaceAll('_', ' ')})`
    default: return event.type
  }
}
