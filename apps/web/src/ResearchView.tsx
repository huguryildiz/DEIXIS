import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpDown, BadgeCheck, BookOpen, BookOpenText, CalendarDays, Download, FileText, FileUp, Link2, MessageSquareQuote, Pause, Play, Quote, ScanSearch, Search, ShieldCheck, Sparkles, Trash2, UserPen, Users, X, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, ApiError, assetUrl, bibliographyUrl, subscribe, type ActivityEvent, type Answer, type ModelOption, type ResearchView, type Run, type RunStatus, type Source, type ValidationIssue, type Verdict, type ZoteroSource } from './api'
import { accessParts, citedText, locatorText, pauseReasonText, providerName, runStatusLabels, scopeLabels, stepLabel, verdictLabels, versionText } from './labels'
import { PassageSheet } from './PassageSheet'
import { MathText } from './MathText'
import { Transcript } from './Transcript'
import { ZoteroPanel } from './ZoteroPanel'
import { useToast } from './Toast'
import { ConnectionIcon } from './connectionIcons'
import { ConfirmDialog } from './ConfirmDialog'
import { effortLabels, effortOptions, modelRoles, Option, scopeOptions } from './Home'
import { citationStyles, formatReference, type CitationStyle } from './citations'
import { t, uiLocale } from './i18n'

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function ResearchPage({ id, initialTab, dark, onChanged }: { id: string; initialTab?: string; dark: boolean; onChanged: () => void }) {
  const [view, setView] = useState<ResearchView | null>(null)
  const [error, setError] = useState('')
  const toast = useToast()
  const [tab, setTab] = useState(initialTab === 'sources' || initialTab === 'activity' ? initialTab : 'answer')
  const [passageTarget, setPassageTarget] = useState<{ passageId: string; highlightText: string | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [pdfFinding, setPdfFinding] = useState<string | null>(null)
  const [attachTarget, setAttachTarget] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<{ source: Source; assetId: string } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const sourceFileInput = useRef<HTMLInputElement>(null)
  const firstEvent = useRef<number | null>(null)
  const tabsRef = useRef<HTMLDivElement>(null)
  const jumped = useRef(false)
  const lastRun = useRef<{ id: string; status: RunStatus } | null>(null)

  const load = useCallback(async () => {
    try { const next = await api.research(id); setView(next); setError(''); if (firstEvent.current === null) firstEvent.current = next.last_event_id } catch (e) { setError(errorText(e)) }
  }, [id])
  useEffect(() => { void load() }, [load])
  // Codex lists each model's default effort; a research created without an effort runs at that default.
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  useEffect(() => { api.connections().then(c => setModelOptions(Object.values(c.models).flatMap(h => h.models ?? []))).catch(() => { /* efforts stay unlabelled */ }) }, [])

  const loaded = view !== null
  useEffect(() => {
    // Opened at a tab (e.g. from quick find): bring the tabs into view and put keyboard focus on the chosen tab.
    if (!loaded || !initialTab || jumped.current) return
    jumped.current = true
    tabsRef.current?.scrollIntoView({ block: 'start' })
    tabsRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus({ preventScroll: true })
  }, [loaded, initialTab])

  useEffect(() => {
    if (!loaded) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const stop = subscribe(id, firstEvent.current ?? 0, () => { clearTimeout(timer); timer = setTimeout(() => { void load(); onChanged() }, 250) })
    return () => { stop(); clearTimeout(timer) }
  }, [id, loaded, load, onChanged])

  useEffect(() => {
    if (tab !== 'activity') return
    api.events(id).then(setEvents).catch(e => toast('error', t('Could not load activity: {error}', { error: errorText(e) })))
  }, [tab, id, view?.last_event_id, toast])

  // Runs finish in the background, often while another tab is open: announce each status change of the latest run.
  useEffect(() => {
    const current = view?.runs[0]
    if (!view || !current) return
    const previous = lastRun.current
    lastRun.current = { id: current.id, status: current.status }
    if (!previous || (previous.id === current.id && previous.status === current.status)) return
    const label = t(current.kind === 'discovery' ? 'Search & screening' : 'Answer generation')
    const reason = pauseReasonText(current.pause_reason)
    if (previous.id !== current.id) { if (ACTIVE.has(current.status)) toast('success', t('{label} started.', { label })); return }
    switch (current.status) {
      case 'completed': {
        const answer = view.answers.find(a => a.run_id === current.id)
        if (current.kind === 'discovery') toast('success', t('Search & screening finished. Review the sources and include the ones to use.'))
        else if (answer?.status === 'structurally_valid') toast('success', t('Answer ready.'))
        else if (answer?.status === 'clarification') toast('warning', t('The model needs a clarification before it can answer.'))
        else if (answer?.status === 'no_evidence') toast('warning', t('No answer: no text passages were available for the included sources.'))
        else toast('warning', t('The answer failed validation; it is kept as an unverified draft.'))
        break
      }
      case 'paused': toast(current.pause_reason === 'user_requested' ? 'success' : 'warning', t('{label} paused. {reason}', { label, reason })); break
      case 'failed': toast('error', t('{label} failed. {reason}', { label, reason })); break
      case 'cancelled': toast('success', t('{label} cancelled.', { label })); break
      case 'pause_requested': toast('success', t('Pause requested: the run stops after the current call.')); break
      case 'queued': case 'running': if (previous.status === 'paused') toast('success', t('{label} resumed.', { label })); break
    }
  }, [view, toast])

  async function act(action: () => Promise<unknown>, success?: string) {
    setBusy(true)
    try { await action(); if (success) toast('success', success); await load(); onChanged() }
    catch (e) {
      // 409: the research or run changed after this page loaded (another tab, or a run that moved on).
      if (e instanceof ApiError && e.status === 409) { toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message })); await load() }
      else toast('error', errorText(e))
    } finally { setBusy(false) }
  }

  if (error && !view) return <section className="research-view"><div className="legacy-boundary">{t('Could not open this research: {error}', { error })}</div></section>
  if (!view) return <section className="research-view"><p className="session-meta">{t('Loading research…')}</p></section>

  const run = view.runs[0] as Run | undefined
  const active = run ? ACTIVE.has(run.status) : false
  const answer = view.answers[0] as Answer | undefined
  const hasAcademic = view.scope.source_scope !== 'attached'
  const included = view.counts.included

  const startAnswer = () => act(() => api.startRun(id, 'answer', crypto.randomUUID()))
  const startDiscovery = () => act(() => api.startRun(id, 'discovery', crypto.randomUUID()))
  const upload = (list: FileList | null) => list && act(async () => { for (const file of Array.from(list)) await api.upload(id, file) }, t('PDF added and included. Its text was extracted page by page (no OCR).'))
  const uploadToSource = (list: FileList | null) => list && attachTarget && act(async () => {
    for (const file of Array.from(list)) await api.uploadToSource(id, attachTarget, file)
  }, t('PDF attached to this source. Its text was extracted page by page (no OCR).'))
  const discoverPdf = async (source: Source) => {
    setPdfFinding(source.source_version_id)
    try { await api.discoverPdf(id, source.source_version_id); await load(); onChanged() }
    catch (e) { toast('error', errorText(e)) }
    finally { setPdfFinding(null) }
  }
  const chooseSourcePdf = (source: Source) => { setAttachTarget(source.source_version_id); sourceFileInput.current?.click() }
  const removeSourcePdf = (source: Source, assetId: string) => setRemoveTarget({ source, assetId })
  const confirmRemoveSourcePdf = () => {
    if (!removeTarget) return
    const { source, assetId } = removeTarget
    setRemoveTarget(null)
    void act(() => api.removeAsset(id, source.source_version_id, assetId), t('PDF removed from the source.'))
  }
  const importZotero = (source: ZoteroSource, key: string) => act(async () => {
    const { items, pdfs_added: pdfs, notes } = (await api.zoteroImport(id, source, key)).zotero_import
    setZoteroOpen(false)
    const added = `${t(items === 1 ? '{n} Zotero item added and included;' : '{n} Zotero items added and included;', { n: items })} ${t(pdfs === 1 ? '{n} PDF read page by page (no OCR).' : '{n} PDFs read page by page (no OCR).', { n: pdfs })}`
    if (notes.length) toast('warning', `${added} ${notes.map(n => `${n.title}: ${n.note}.`).join(' ')}`)
    else toast('success', added)
  })

  const ScopeIcon = scopeOptions[view.scope.source_scope].icon
  const EffortIcon = effortOptions[view.scope.effort].icon
  const modelText = (model: string | null, effort: string | null) => {
    if (!model) return t('no model chosen')
    const eff = effort || modelOptions.find(m => m.id === model)?.default_reasoning_effort
    return eff ? `${model}-${eff}` : model
  }
  const literatureConnection = view.scope.literature_model ? view.scope.literature_connection ?? view.scope.model_connection : view.scope.model_connection
  const reviewerConnection = view.reviewer.connection ?? view.scope.model_connection
  return <section className="research-view legacy-research">
    <div className="section-label">{t('RESEARCH')} <span> {t('/ REVISION {n}', { n: view.research.current_scope_revision })}</span></div>
    <h1>{view.scope.question}</h1>
    <div className="session-meta session-chips">
      <span className="meta-chip" title={t('Where DEIXIS looks for sources')}><ScopeIcon size={14} aria-hidden />{t(scopeLabels[view.scope.source_scope])}</span>
      <span className="meta-chip" title={t('How much searching and reading a run may do')}><EffortIcon size={14} aria-hidden />{t('{effort} depth', { effort: t(effortLabels[view.scope.effort]) })}</span>
      <span className="meta-chip" title={t('Writes the source-linked answer')}><modelRoles.answer.icon size={14} aria-hidden />{t('Answer')} · <ConnectionIcon id={view.scope.model_connection} /><span className="sr-only">{connectionName(view.scope.model_connection)} </span>{modelText(view.scope.requested_model, view.scope.reasoning_effort)}</span>
      {/* A research without a literature model (created before model roles) searches with its research model. */}
      <span className="meta-chip" title={t('Plans the searches and screens the candidates')}><ScanSearch size={14} aria-hidden />{t('Literature')} · <ConnectionIcon id={literatureConnection} /><span className="sr-only">{connectionName(literatureConnection)} </span>{modelText(view.scope.literature_model ?? view.scope.requested_model, view.scope.literature_model ? view.scope.literature_reasoning_effort : view.scope.reasoning_effort)}</span>
      <span className="meta-chip" title={t('Reviews each claim against its cited passages when an answer completes; never changes the answer')}><ShieldCheck size={14} aria-hidden />{view.reviewer.model ? <>{t('Reviewer')} · <ConnectionIcon id={reviewerConnection} /><span className="sr-only">{connectionName(reviewerConnection)} </span>{modelText(view.reviewer.model, view.reviewer.reasoning_effort)}{view.reviewer.mode === 'default' && ` ${t('(default)')}`}</> : t(view.reviewer.mode === 'off' ? 'Reviewer off' : 'No reviewer set')}</span>    </div>

    {/* Counts and run controls sit above the tabs so they stay reachable from Sources and Activity; the Answer tab tells the run step by step. */}
    {(run || view.sources.length > 0) && <div className={`legacy-progress run-card${run ? ` is-${run.status}` : ''}`}>
      {run && <div className="legacy-progress-head">
        <strong>{t(run.kind === 'discovery' ? 'Search & screening' : 'Answer')} · {t(runStatusLabels[run.status])}</strong>
        {(active || run.status === 'paused') && <div className="run-actions">
          {active && run.status !== 'pause_requested' && <Button variant="outline" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'pause'))}><Pause size={14} />{t('Pause')}</Button>}
          {run.status === 'paused' && <Button variant="default" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'resume'))}><Play size={14} />{t('Resume')}</Button>}
          <Button variant="destructive" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'cancel'))}><X size={14} />{t('Cancel')}</Button>
        </div>}
      </div>}
      <div className="legacy-counts run-counts" title={t('Unique, included, given and cited count works: versions of one work count once. “Given to the model” counts works whose passages were sent in the latest answer step; it is not a full-text reading claim.')}>
        {([['found', 'Found'], ['unique', 'Unique works'], ['included', 'Included'], ['inspected', 'Given to the model'], ['cited', 'Cited']] as const).map(([key, label]) => <div key={key}><strong>{view.counts[key]}</strong><span>{t(label)}</span></div>)}
      </div>
    </div>}

    <div ref={tabsRef}><Tabs className="research-tabs" value={tab} onValueChange={value => setTab(String(value))}>
      <TabsList><TabsTrigger value="answer">{t('Answer')}</TabsTrigger><TabsTrigger value="sources">{t('Sources')} <span className="research-tab-count">{view.sources.length}</span></TabsTrigger><TabsTrigger value="activity">{t('Activity')}</TabsTrigger></TabsList>

      <TabsContent value="answer">
        <Transcript view={view} modelText={modelText}
          emptyText={included ? t(included === 1 ? '{n} source is included. Generate an answer when your selection is ready.' : '{n} sources are included. Generate an answer when your selection is ready.', { n: included }) : t(hasAcademic ? 'Start an academic search, or attach PDFs.' : 'Attach PDFs, then generate an answer.')}
          latestAnswer={answer ? <AnswerBlock researchId={id} answer={answer} sources={view.sources} busy={busy} onOpen={(passageId, highlightText) => setPassageTarget({ passageId, highlightText })} onAttachPdf={chooseSourcePdf} /> : null} />
        <div className="answer-actions">
          <Button disabled={busy || active || !included} onClick={startAnswer}><Sparkles size={15} />{t(answer ? 'Generate a new answer' : 'Generate source-linked answer')}</Button>
          {hasAcademic && <Button variant="outline" disabled={busy || active} onClick={startDiscovery}><Search size={15} />{t(view.search_runs.length ? 'Search again' : 'Search providers')}</Button>}
        </div>
      </TabsContent>

      <TabsContent value="sources">
        <div className="legacy-section-head"><div><div className="section-label">{t('SELECTION')}</div><h2>{t('Sources and access')}</h2><p>{t('Your choice always overrides the model’s screening proposal. Access, retrieval and inspection are separate states.')}</p></div>
          <div className="section-actions">
            {included > 0 && <ExportLinks researchId={id} sources="included" />}
            {view.scope.source_scope !== 'academic' && <>
              <div className="source-add-actions">
                <Button className="source-action" variant="outline" disabled={busy} aria-expanded={zoteroOpen} onClick={() => setZoteroOpen(open => !open)}><ConnectionIcon id="zotero" />{t('Add from Zotero')}</Button>
                <Button className="source-action is-primary" variant="outline" disabled={busy} onClick={() => fileInput.current?.click()}><FileUp size={16} />{t('Attach PDF')}</Button>
              </div>
            </>}
          </div></div>
        {zoteroOpen && <ZoteroPanel busy={busy} onImport={importZotero} onClose={() => setZoteroOpen(false)} />}
        {view.search_runs.length > 0 && <div className="search-summary">{view.search_runs.map(s => <div key={s.id}><Search size={13} /><span>“{s.query_text}”</span><small>{providerName(s.provider)} · {t(s.status.replace('_', ' '))} · {t('{count} of {total} records', { count: s.result_count, total: s.provider_total ?? '?' })} · {t(s.access_mode)}{s.scope_revision !== view.research.current_scope_revision ? ` ${t('· for question revision {n}', { n: s.scope_revision })}` : ''}</small></div>)}</div>}
        <SourceList sources={view.sources} busy={busy}
          onSelect={(source, state) => act(() => api.select(id, source.source_version_id, state, source.selection.version))}
          onReason={(source, reason) => act(() => api.select(id, source.source_version_id, source.selection.state, source.selection.version, reason), t('Reason saved with your choice.'))}
          onAbstract={source => source.access.abstract_passage_id && setPassageTarget({ passageId: source.access.abstract_passage_id, highlightText: null })}
          onDiscoverPdf={source => { void discoverPdf(source) }} onAttachPdf={chooseSourcePdf}
          onRemoveAsset={removeSourcePdf} researchId={id} pdfFinding={pdfFinding} />
      </TabsContent>

      <TabsContent value="activity">
        <ol className="activity-list">{events.slice().reverse().map(event => {
          const { icon, text, chips } = describeEvent(event)
          return <li key={event.id}>
            <time>{new Date(event.created_at).toLocaleString(uiLocale())}</time>
            <span className="activity-event"><span className="activity-icon">{icon}</span><span>{text}</span>{chips.map((chip, i) => <span key={i} className={`activity-chip is-${chip.tone}`}>{chip.label}</span>)}</span>
          </li>
        })}</ol>
        {!events.length && <p className="empty-inline">{t('No recorded activity.')}</p>}
      </TabsContent>
    </Tabs></div>
    {/* Outside the tabs: the answer's PDF suggestions attach through the same picker as the Sources tab. */}
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void upload(e.target.files); e.target.value = '' }} />
    <input ref={sourceFileInput} type="file" accept=".pdf,application/pdf" hidden onChange={e => { void uploadToSource(e.target.files); e.target.value = '' }} />

    <RevisionForm key={view.research.version} question={view.scope.question} disabled={busy || active}
      onSubmit={text => act(() => api.reviseScope(id, text, view.research.version), t('Question revised. Earlier answers stay visible and are marked as belonging to the previous revision.'))} />
    <ConfirmDialog open={Boolean(removeTarget)} dark={dark} title={t('Remove PDF?')}
      description={t('This PDF will not be used in future answers. Existing answers that used the source will be marked outdated.')}
      context={removeTarget?.source.title} confirmLabel={t('Remove PDF')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={confirmRemoveSourcePdf} onOpenChange={open => { if (!open) setRemoveTarget(null) }} />
    <PassageSheet researchId={id} passageId={passageTarget?.passageId ?? null} highlightText={passageTarget?.highlightText} dark={dark} onClose={() => setPassageTarget(null)} />
  </section>
}

const versionTones: Record<string, string> = { publishedVersion: 'published', acceptedVersion: 'accepted', submittedVersion: 'submitted' }

function AnswerBlock({ researchId, answer, sources, busy, onOpen, onAttachPdf }: { researchId: string; answer: Answer; sources: Source[]; busy: boolean; onOpen: (passageId: string, highlightText: string | null) => void; onAttachPdf: (source: Source) => void }) {
  const [style, setStyle] = useState<CitationStyle>(() => { try { const saved = localStorage.getItem('deixis-citation-style'); return saved && Object.keys(citationStyles).includes(saved) ? saved as CitationStyle : 'apa' } catch { return 'apa' } })
  const chooseStyle = (next: CitationStyle) => { setStyle(next); try { localStorage.setItem('deixis-citation-style', next) } catch { /* the choice still applies for this tab */ } }
  if (answer.status === 'clarification' && answer.clarification) {
    return <div className="legacy-answer"><div className="section-label">{t('CLARIFICATION NEEDED')}</div><h2>{answer.clarification.question}</h2><p>{answer.clarification.why_it_matters}</p>{answer.clarification.options.length > 0 && <ul className="plain-list">{answer.clarification.options.map(o => <li key={o}>{o}</li>)}</ul>}<p className="legacy-mini-note">{t('Revise the question below to continue.')}</p></div>
  }
  if (answer.status === 'no_evidence') {
    return <div className="legacy-boundary">{t('No text passages were available for the included sources (no abstract, no retrievable PDF text). No answer was generated.')}</div>
  }
  if (answer.status === 'unverified_draft') {
    return <div className="legacy-answer"><div className="legacy-boundary">{t('The model output failed validation after one repair attempt, so it is not shown as a cited answer.')}<ul className="plain-list">{answer.validation.issues?.map(i => <li key={`${i.code}${i.path}`}>{t('{code} at {path}', { code: i.code, path: i.path })}</li>)}</ul></div>
      {answer.unverified_draft?.claims?.map(c => <p className="claim is-unverified" key={c.claim_label}><MathText text={c.text} /></p>)}</div>
  }
  const refs = new Map<string, { n: number; e: Answer['claims'][number]['evidence'][number] }>()
  answer.claims.forEach(c => c.evidence.forEach(e => { if (!refs.has(e.passage_id)) refs.set(e.passage_id, { n: refs.size + 1, e }) }))
  // Consecutive claims with the same heading form one report section; answers saved before sections have no heading.
  const sections: { heading: string | null; claims: Answer['claims'] }[] = []
  answer.claims.forEach(c => { const last = sections[sections.length - 1]; if (last && last.heading === c.section) last.claims.push(c); else sections.push({ heading: c.section, claims: [c] }) })
  // An access limitation shown with the PDF suggestions is not repeated under Limits.
  const suggestion = pdfSuggestion(answer, sources)
  const limits = answer.limitations.filter(l => !suggestion?.notes.includes(l))
  return <div className="legacy-answer">
    <div className="section-label">{t('SOURCE-LINKED ANSWER')}{answer.applicability === 'stale_scope' ? ` ${t('· EARLIER QUESTION REVISION')}` : answer.applicability === 'stale_selection' ? ` ${t('· EARLIER SOURCE SELECTION')}` : ''}</div>
    {answer.applicability === 'stale_scope' && <div className="legacy-boundary">{t('This answer was produced for revision {n} of the question and is not applied to the current revision.', { n: answer.scope_revision })}</div>}
    {answer.applicability === 'stale_selection' && <div className="legacy-boundary">{t('Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added.')}</div>}
    {answer.capability_notice && <div className="legacy-boundary">{answer.capability_notice}</div>}
    {sections.map(({ heading, claims }, index) => <section className="answer-section" key={index}>
      {heading && <h3>{heading}</h3>}
      {claims.map(claim => <p className="claim" key={claim.id}>
        <MathText text={claim.text} />{claim.support_type === 'analyst_inference' && <span className="support-badge">{t('interpretation')}</span>}
        {claim.evidence.map(e => <button key={e.passage_id} className="cite-chip" title={`${e.title} · ${versionText(e.version_label)} · ${locatorText(e)}`} onClick={() => onOpen(e.passage_id, e.anchor_text)}>[{refs.get(e.passage_id)?.n}]</button>)}
        {claim.review && <span className={`review-badge is-${claim.review.verdict}`} title={t('Reviewer: {reason}', { reason: claim.review.reason })}><ShieldCheck size={11} aria-hidden />{t(verdictLabels[claim.review.verdict])}</span>}
        {claim.review && claim.review.verdict !== 'supported' && <small className="review-reason">{t('Reviewer: {reason}', { reason: claim.review.reason })}</small>}
      </p>)}
    </section>)}
    {!answer.claims.length && <p>{t('No claim could be linked to the passages given to the model.')}</p>}
    {answer.unanswered_aspects.length > 0 && <><h3>{t('Not answered by the inspected passages')}</h3><ul className="plain-list">{answer.unanswered_aspects.map(a => <li key={a}><MathText text={a} /></li>)}</ul></>}
    {limits.length > 0 && <><h3>{t('Limits')}</h3><ul className="plain-list">{limits.map((l, i) => <li key={i}><em>{t(l.kind.replace('_', ' '))}:</em> <MathText text={l.text} /></li>)}</ul></>}
    {refs.size > 0 && <>
      <div className="reference-head"><h3>{t('Cited passages')}</h3>
        <div className="reference-tools"><ExportLinks researchId={researchId} sources="cited" />
        <Select value={style} onValueChange={value => { if (value) chooseStyle(value as CitationStyle) }}>
          <SelectTrigger aria-label={t('Citation style')} title={t('How the cited sources are written')}><SelectValue>{(value: string) => <><Quote size={14} />{t(citationStyles[value as CitationStyle].label)}</>}</SelectValue></SelectTrigger>
          <SelectContent className="intake-select-content has-details" align="end" alignItemWithTrigger={false}>
            <div className="intake-select-heading" aria-hidden="true">{t('CITATION STYLE')}</div>
            {(Object.keys(citationStyles) as CitationStyle[]).map(k => <SelectItem key={k} value={k}><Option icon={Quote} title={t(citationStyles[k].label)} detail={t(citationStyles[k].detail)} /></SelectItem>)}
          </SelectContent>
        </Select></div>
      </div>
      <ol className="reference-list">{[...refs.values()].map(({ n, e }) => {
        const source = sources.find(s => s.source_version_id === e.source_version_id)
        const locator = locatorText(e)
        return <li key={e.passage_id}><button onClick={() => onOpen(e.passage_id, e.anchor_text)}>
          <span className="ref-num">[{n}]</span>
          <span className="ref-body">
            <span className="ref-text">{source ? formatReference(style, source) : e.title}</span>
            <span className="ref-pills">
              <span className={`ref-pill ${e.kind === 'abstract' ? 'is-abstract' : 'is-text'}`}>{e.kind === 'abstract' ? <BookOpenText size={12} aria-hidden /> : <FileText size={12} aria-hidden />}{locator.charAt(0).toUpperCase() + locator.slice(1)}</span>
              <span className={`ref-pill is-${versionTones[e.version_label ?? ''] ?? 'unstated'}`}><BadgeCheck size={12} aria-hidden />{versionText(e.version_label)}</span>
            </span>
          </span>
        </button></li>
      })}</ol>
    </>}
    <p className="legacy-mini-note">{t('Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked.')} {answer.model ? t('Model: {connection} · {model}.', { connection: answer.model.connection, model: answer.model.resolved_model ?? answer.model.requested_model ?? t('unknown') }) : ''} {answer.inputs_given ? t('{passages} passages from {sources} sources were provided.', { passages: answer.inputs_given.passages, sources: answer.inputs_given.sources }) : ''}</p>
    <ReviewNote review={answer.review} />
    <ChecksNote warnings={answer.validation.warnings} />
    {suggestion && <PdfSuggestions notes={suggestion.notes} sources={suggestion.sources} busy={busy} onAttachPdf={onAttachPdf} />}
  </div>
}

// Sources the answer could read only from their abstracts and that still have no PDF. The model's access limitations name
// them and say what their full text would settle; an answer without such a limitation lists its cited sources that lack a PDF.
function pdfSuggestion(answer: Answer, sources: Source[]): { notes: Limitation[]; sources: Source[] } | null {
  if (answer.status !== 'structurally_valid' || answer.applicability === 'stale_scope') return null
  const lacking = (ids: string[]) => [...new Set(ids)]
    .map(id => sources.find(s => s.source_version_id === id && s.origin === 'provider' && !s.access.assets.length))
    .filter((s): s is Source => Boolean(s))
  const notes = answer.limitations.filter(l => l.kind === 'access' && lacking(l.source_ids).length > 0)
  const listed = lacking(notes.length ? notes.flatMap(l => l.source_ids) : answer.claims.flatMap(c => c.evidence.map(e => e.source_version_id)))
  return listed.length ? { notes, sources: listed } : null
}

// A short author–year key such as "Gur23": the first author's family name, then the last two digits of the year.
function sourceKey(source: Source) {
  const author = source.authors[0]?.trim()
  const name = author ? (author.includes(',') ? author.split(',')[0] : author.split(/\s+/).pop() ?? '') : source.title
  const stem = name.replace(/ı/g, 'i').normalize('NFD').replace(/[^A-Za-z]/g, '').slice(0, 3)
  return stem ? `${stem.charAt(0).toUpperCase()}${stem.slice(1).toLowerCase()}${source.year ? String(source.year).slice(-2) : ''}` : ''
}

function PdfSuggestions({ notes, sources, busy, onAttachPdf }: { notes: Limitation[]; sources: Source[]; busy: boolean; onAttachPdf: (source: Source) => void }) {
  const tip = t('Sources the answer read only from their abstracts and that have no PDF yet. An attached PDF is read page by page (no OCR).')
  return <section className="pdf-suggest" aria-labelledby="pdf-suggest-title">
    <div className="pdf-suggest-head">
      <Upload size={18} aria-hidden />
      <div>
        <strong id="pdf-suggest-title">{t('PDF uploads suggested')}<span className="pdf-suggest-info" title={tip}><Info size={14} aria-hidden /><span className="sr-only">{tip}</span></span></strong>
        <small>{t('Attached PDFs stay with this research; generate a new answer to use their text.')}</small>
      </div>
    </div>
    <div className="pdf-suggest-body">
      {notes.length ? notes.map((l, i) => <p key={i}><MathText text={l.text} /></p>)
        : <p>{t('The answer cited these sources from their abstracts only. Their full text can add details the abstracts leave out.')}</p>}
      <ul className="pdf-suggest-list">{sources.map(source => {
        const key = sourceKey(source)
        const href = source.doi ? `https://doi.org/${source.doi}` : source.landing_url
        return <li key={source.source_version_id}>
          {key && <span className="pdf-suggest-key" title={[source.authors.join(', '), source.year].filter(Boolean).join(' · ')}>{key}</span>}
          <span className="pdf-suggest-title" title={source.title}>{source.title}</span>
          <span className="pdf-suggest-actions">
            {href && <a href={href} target="_blank" rel="noreferrer" title={t('Opens the source page in a new tab')}><ArrowUpRight size={14} aria-hidden />{t('Get PDF')}</a>}
            <button type="button" disabled={busy} onClick={() => onAttachPdf(source)} aria-label={t('Attach a PDF to {title}', { title: source.title })}><Upload size={14} aria-hidden />{t('Attach PDF')}</button>
          </span>
        </li>
      })}</ul>
    </div>
  </section>
}

const phrasingCodes = new Set(['sentence_without_phrasebank_frame', 'own_work_phrase_in_claim', 'plural_sources_for_one_source'])
const mathLabels: Record<string, string> = {
  math_not_well_formed: 'Math is not well formed',
  math_without_full_text: 'Math cites abstract text only',
  anchor_not_in_passage: 'Citation opens without a highlight',
  missing_citation_anchor: 'Citation opens without a highlight',
}
const checkCodes = new Set([...phrasingCodes, ...Object.keys(mathLabels)])

// Prose and math findings are listed with the answer; they never reject it (D19).
function ChecksNote({ warnings }: { warnings?: ValidationIssue[] }) {
  const found = (warnings ?? []).filter(w => checkCodes.has(w.code))
  if (!found.length) return null
  const phrasingOnly = found.every(w => phrasingCodes.has(w.code))
  const summary = phrasingOnly
    ? (found.length === 1 ? 'Phrasing check: {n} finding. It does not reject the answer.' : 'Phrasing check: {n} findings. They do not reject the answer.')
    : (found.length === 1 ? 'Answer checks: {n} finding. It does not reject the answer.' : 'Answer checks: {n} findings. They do not reject the answer.')
  return <details className="legacy-mini-note phrasing-note">
    <summary>{t(summary, { n: found.length })}</summary>
    <ul className="plain-list">{found.map((w, i) => <li key={i}>{mathLabels[w.code] && <strong>{t(mathLabels[w.code])}: </strong>}{w.message}</li>)}</ul>
  </details>
}


function ReviewNote({ review }: { review: Answer['review'] }) {
  if (!review) return null
  const model = review.model ? review.model.resolved_model ?? review.model.requested_model : null
  if (review.status === 'failed') {
    return <p className="legacy-mini-note review-summary"><ShieldCheck size={13} aria-hidden />{model ? t('The reviewer ({model}) did not produce a usable review.', { model }) : t('The reviewer did not produce a usable review.')} {pauseReasonText(review.failure_reason)} {t('The answer is unchanged.')}</p>
  }
  const counts = (Object.keys(verdictLabels) as Verdict[]).map(v => [v, review.reviews.filter(r => r.verdict === v).length] as const).filter(([, n]) => n > 0)
  return <p className="legacy-mini-note review-summary"><ShieldCheck size={13} aria-hidden /><span><strong>{t('Reviewer')}{model ? ` · ${model}` : ''}:</strong> {counts.map(([v, n]) => `${n} ${t(verdictLabels[v])}`).join(' · ')}. {review.notes && `${review.notes} `}{t('This is an additional model’s reading of each claim against its cited passages. It does not change the answer and is not independent verification.')}</span></p>
}

// Bibliography files for reference managers, downloaded from the local API.
function ExportLinks({ researchId, sources }: { researchId: string; sources: 'included' | 'cited' }) {
  const label = t(sources === 'included' ? 'included sources' : 'cited sources')
  return <span className="export-links" role="group" aria-label={t('Export {label}', { label })}>
    <span className="export-links-label"><Download size={15} aria-hidden />{t(sources === 'included' ? 'Export included' : 'Export cited')}</span>
    <span className="export-formats">
      <a href={bibliographyUrl(researchId, 'bibtex', sources)} download title={t('BibTeX file of the {label} (LaTeX, Zotero, JabRef)', { label })}>.bib</a>
      <a href={bibliographyUrl(researchId, 'ris', sources)} download title={t('RIS file of the {label} (Zotero, EndNote, Mendeley)', { label })}>.ris</a>
    </span>
  </span>
}

function ReasonForm({ busy, onSave }: { busy: boolean; onSave: (reason: string) => void }) {
  const [text, setText] = useState('')
  return <form className="reason-form" onSubmit={e => { e.preventDefault(); if (text.trim()) onSave(text.trim()) }}>
    <input aria-label={t('Reason for excluding this source')} placeholder={t('Why exclude it? Optional; kept with your choice.')} maxLength={1000} value={text} onChange={e => setText(e.target.value)} />
    <Button type="submit" variant="outline" size="sm" disabled={busy || !text.trim()}>{t('Save reason')}</Button>
  </form>
}

type SourceSort = 'found' | 'relevant' | 'cited' | 'newest' | 'oldest' | 'title'
const sourceSorts: Record<SourceSort, string> = { found: 'Order found', relevant: 'Most relevant', cited: 'Most cited', newest: 'Newest first', oldest: 'Oldest first', title: 'Title A–Z' }
// Search position is not comparable across queries: the model's screening verdict decides, then similarity to the question
// when semantic search scored the source (D30), then the best position in the searches that found it.
const verdictOrder: Record<string, number> = { include: 0, uncertain: 1, exclude: 2 }
const verdictRank = (s: Source) => verdictOrder[s.selection.proposal ?? ''] ?? 3
const stateFilters = [['all', 'All'], ['included', 'Included'], ['pending', 'Undecided'], ['excluded', 'Excluded']] as const
type StateFilter = typeof stateFilters[number][0]
// Sources without the value (no year, no citation count) go last in either direction.
const byNumber = (a: number | null, b: number | null, dir: 1 | -1) => a === null ? (b === null ? 0 : 1) : b === null ? -1 : dir * (a - b)
const sourceCompare: Record<SourceSort, (a: Source, b: Source) => number> = {
  found: () => 0,
  relevant: (a, b) => verdictRank(a) - verdictRank(b) || byNumber(a.similarity, b.similarity, -1) || byNumber(a.rank, b.rank, 1),
  cited: (a, b) => byNumber(a.cited_by_count, b.cited_by_count, -1),
  newest: (a, b) => byNumber(a.year, b.year, -1),
  oldest: (a, b) => byNumber(a.year, b.year, 1),
  title: (a, b) => a.title.localeCompare(b.title),
}

type SourceActions = { onSelect: (source: Source, state: Source['selection']['state']) => void; onReason: (source: Source, reason: string) => void; onAbstract: (source: Source) => void; onDiscoverPdf: (source: Source) => void; onAttachPdf: (source: Source) => void; onRemoveAsset: (source: Source, assetId: string) => void; researchId: string; pdfFinding: string | null }

function SourceList({ sources, busy, onSelect, onReason, onAbstract, onDiscoverPdf, onAttachPdf, onRemoveAsset, researchId, pdfFinding }: { sources: Source[]; busy: boolean } & SourceActions) {
  const [filter, setFilter] = useState<StateFilter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SourceSort>('found')
  // Other versions follow their record and move with it; the filter and sort look at the record.
  const families: Source[][] = []
  for (const source of sources) {
    const last = families[families.length - 1]
    if (source.version_role === 'other_version' && last?.[0].work_id === source.work_id) last.push(source)
    else families.push([source])
  }
  const counts = { all: families.length, included: 0, pending: 0, excluded: 0 }
  families.forEach(([record]) => counts[record.selection.state]++)
  const needle = query.trim().toLocaleLowerCase()
  const matches = (s: Source) => [s.title, s.venue, s.doi, ...s.authors].some(text => text?.toLocaleLowerCase().includes(needle))
  const shown = families.filter(f => (filter === 'all' || f[0].selection.state === filter) && (!needle || f.some(matches)))
    .sort((a, b) => sourceCompare[sort](a[0], b[0]))
  if (!sources.length) return <p className="empty-inline">{t('No sources yet.')}</p>
  return <>
    {families.length > 1 && <div className="source-toolbar">
      <div className="source-filters" role="group" aria-label={t('Show sources')}>
        {stateFilters.map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{t(label)}<span>{counts[key]}</span></button>)}
      </div>
      <label className="source-search"><Search size={14} aria-hidden /><input type="search" aria-label={t('Filter sources')} placeholder={t('Title, author, venue or DOI')} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <Select value={sort} onValueChange={value => { if (value) setSort(value as SourceSort) }}>
        <SelectTrigger aria-label={t('Sort sources')}><SelectValue>{(value: string) => <><ArrowUpDown size={14} />{t(sourceSorts[value as SourceSort])}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content" align="end" alignItemWithTrigger={false}>
          {(Object.keys(sourceSorts) as SourceSort[]).map(k => <SelectItem key={k} value={k}>{k === 'relevant' ? <span className="sort-option">{t(sourceSorts[k])}<small>{t('Model’s screening verdict first, then similarity to the question, then search position')}</small></span> : t(sourceSorts[k])}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>}
    {shown.flat().map(source => <SourceRow key={source.source_version_id} source={source} busy={busy}
      onSelect={state => onSelect(source, state)} onReason={reason => onReason(source, reason)} onAbstract={() => onAbstract(source)}
      onDiscoverPdf={() => onDiscoverPdf(source)} onAttachPdf={() => onAttachPdf(source)}
      onRemoveAsset={assetId => onRemoveAsset(source, assetId)} researchId={researchId} finding={pdfFinding === source.source_version_id} />)}
    {!shown.length && <p className="empty-inline source-empty">{t('No source matches this filter.')} <button onClick={() => { setFilter('all'); setQuery('') }}>{t('Show all sources')}</button></p>}
  </>
}

function SourceRow({ source, busy, onSelect, onReason, onAbstract, onDiscoverPdf, onAttachPdf, onRemoveAsset, researchId, finding }: { source: Source; busy: boolean; onSelect: (state: Source['selection']['state']) => void; onReason: (reason: string) => void; onAbstract: () => void; onDiscoverPdf: () => void; onAttachPdf: () => void; onRemoveAsset: (assetId: string) => void; researchId: string; finding: boolean }) {
  const s = source.selection
  const other = source.version_role === 'other_version'
  const authors = source.authors.join(', ')
  const citationDetails = [source.volume && t('vol. {value}', { value: source.volume }), source.issue && t('no. {value}', { value: source.issue }), source.pages && t('pp. {value}', { value: source.pages })].filter(Boolean).join(' · ')
  const meta: [LucideIcon, string | number | null | false][] = [[Users, authors], [CalendarDays, source.year], [BookOpen, source.venue], [BookOpen, citationDetails], [Quote, citedText(source.cited_by_count)], [Search, source.provider_records.map(providerName).join(', ')]]
  const shown = meta.filter(([, text]) => text)
  return <div className={`source-row is-${s.state}${other ? ' is-other-version' : ''}`}>
    <div className="source-main">
      {other && <span className="version-note">{t('Another version of the record above: {version}. It is not screened separately; passages cited from it are labelled with this version.', { version: versionText(source.version_label) })}</span>}
      <strong>{source.title}</strong>
      <div className="source-meta">
        {shown.length ? shown.map(([Icon, text], i) => <span key={i}><Icon size={13} aria-hidden />{text}</span>)
          : <span>{t(source.origin === 'user_upload' ? 'Uploaded PDF' : 'No bibliographic details from the provider')}</span>}
      </div>
      <div className="ref-pills source-pills">
        {source.version_label && <span className={`ref-pill is-${versionTones[source.version_label] ?? 'unstated'}`}><BadgeCheck size={12} aria-hidden />{versionText(source.version_label)}</span>}
        {accessParts(source).map(part => <span key={part.text} className={`ref-pill is-${part.tone}`}>{part.tone === 'abstract' ? <BookOpenText size={12} aria-hidden /> : <FileText size={12} aria-hidden />}{part.text}</span>)}
        {source.similarity !== null && <span className="ref-pill is-similarity" title={t(source.access.abstract_passage_id ? 'Embedding similarity between the research question and this source’s title and stored abstract. Used for ordering only; it is not a relevance judgment.' : 'Embedding similarity between the research question and this source’s title. No abstract was available. Used for ordering only; it is not a relevance judgment.')}><ScanSearch size={12} aria-hidden />{t('Similarity {score}', { score: source.similarity.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })}</span>}
        {source.suspected_duplicates.length > 0 && <span className="ref-pill is-unstated" title={source.suspected_duplicates.map(d => t(d.basis === 'published_doi' ? 'a preprint that names the other record’s DOI' : 'same title')).join('; ')}><FileText size={12} aria-hidden />{t(source.suspected_duplicates.length === 1 ? 'may duplicate {n} other source · not merged' : 'may duplicate {n} other sources · not merged', { n: source.suspected_duplicates.length })}</span>}
        {source.cited_in_latest_answer && <span className="ref-pill is-cited"><MessageSquareQuote size={12} aria-hidden />{t('cited in the latest answer')}</span>}
      </div>
      {finding && <p className="pdf-search-status" role="status"><Search size={13} aria-hidden /><span className="shimmer-text">{t('Checking Unpaywall, OpenAlex and Crossref; Web Search will run if no verified PDF is retrieved…')}</span></p>}
      {!finding && source.access.pdf_discoveries.length > 0 && <div className="pdf-candidate-list">
        {source.access.pdf_discoveries.map((search, i) => <span key={`${search.provider}-${search.created_at}-${i}`}><ConnectionIcon id={search.provider} />{providerName(search.provider)} · {t(search.status.replace('_', ' '))} · {search.result_count}{search.http_status ? ` · HTTP ${search.http_status}` : ''}</span>)}
        {source.access.pdf_candidates.map(candidate => <span key={candidate.id}><ConnectionIcon id={candidate.provider} />{providerName(candidate.provider)} · {t(candidate.version_status === 'match' ? 'version verified' : candidate.version_status === 'different' ? 'different version' : 'version uncertain')} · {candidate.access_status === 'http_error' ? `HTTP ${candidate.http_status ?? '?'}` : t(candidate.access_status.replace('_', ' '))}</span>)}
      </div>}
      {source.applicability === 'stale_scope' && <p className="proposal is-stale">{t(s.proposal ? 'Found for question revision {n}; the proposal below was made for that question. Search again to screen it for the current question.' : 'Found for question revision {n}. Search again to screen it for the current question.', { n: source.found_in_revision ?? '?' })}</p>}
      {s.proposal && <p className="proposal"><Sparkles size={13} aria-hidden />{t('Model proposal:')} <em className={`verdict is-${s.proposal}`}>{t(s.proposal)}</em> — {s.proposal_reason} <span>({t(s.proposal_basis?.replaceAll('_', ' ') ?? '')})</span>{s.origin === 'user' ? ` ${t('· overridden by you')}` : ''}</p>}
      {s.origin === 'user' && s.user_reason && <p className="proposal"><UserPen size={13} aria-hidden />{t('Your reason: {reason}', { reason: s.user_reason })}</p>}
      {s.origin === 'user' && s.state === 'excluded' && !s.user_reason && <ReasonForm busy={busy} onSave={onReason} />}
      <div className="source-links">
        {source.access.abstract_passage_id && <button onClick={onAbstract}><BookOpenText size={14} aria-hidden />{t('Read abstract')}</button>}
        {source.doi && <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" />DOI</a>}
        {source.access.assets.map(asset => <span className="source-asset-actions" key={asset.id}>
          <a href={assetUrl(researchId, asset.id)} target="_blank" rel="noreferrer" title={asset.original_filename ?? undefined}><FileText size={14} aria-hidden />{t('Open PDF')}</a>
          <button className="is-destructive" disabled={busy} onClick={() => onRemoveAsset(asset.id)} title={asset.original_filename ?? undefined}><Trash2 size={14} aria-hidden />{t('Remove PDF')}</button>
        </span>)}
        {source.doi && <button disabled={busy || finding} onClick={onDiscoverPdf}><Search size={14} aria-hidden />{finding ? <span className="shimmer-text">{t('Web Search is running…')}</span> : t(source.access.assets.length ? 'Refresh metadata' : 'Find PDF')}</button>}
        {!source.access.assets.length && <button disabled={busy || finding} onClick={onAttachPdf}><FileUp size={14} aria-hidden />{t('Attach PDF')}</button>}
      </div>
    </div>
    <div className="selection-toggle" role="group" aria-label={t('Selection for {title}', { title: source.title })}>
      {(['included', 'pending', 'excluded'] as const).map(state => <button key={state} className={`is-${state}`} aria-pressed={s.state === state} disabled={busy || s.state === state} onClick={() => onSelect(state)}>{t(state === 'included' ? 'Include' : state === 'excluded' ? 'Exclude' : 'Undecided')}</button>)}
    </div>
  </div>
}

function RevisionForm({ question, disabled, onSubmit }: { question: string; disabled: boolean; onSubmit: (text: string) => void }) {
  const [text, setText] = useState(question)
  return <form className="legacy-followup" onSubmit={e => { e.preventDefault(); if (text.trim() && text.trim() !== question) onSubmit(text.trim()) }}>
    <label htmlFor="revise-question">{t('Revise the question')}</label>
    <textarea id="revise-question" value={text} onChange={e => setText(e.target.value)} />
    <div><span>{t('Creates a new question revision. Sources and earlier answers are kept.')}</span><Button type="submit" disabled={disabled || !text.trim() || text.trim() === question}>{t('Save revision')}</Button></div>
  </form>
}

const selectionStates: Record<string, string> = { included: 'Included', excluded: 'Excluded', pending: 'Undecided' }

type ChipTone = 'ok' | 'bad' | 'warn' | 'live' | 'neutral'
type EventChip = { label: string; tone: ChipTone }

const statusTones: Record<string, ChipTone> = {
  completed: 'ok', succeeded: 'ok', structurally_valid: 'ok',
  partial: 'warn', unverified_draft: 'warn', outcome_unknown: 'warn', rate_limited: 'warn', timeout: 'warn',
  failed: 'bad', auth_required: 'bad', entitlement_missing: 'bad', parse_error: 'bad',
  pending: 'live', running: 'live',
}
const statusChip = (status: unknown): EventChip => ({ label: t(String(status).replaceAll('_', ' ')), tone: statusTones[String(status)] ?? 'neutral' })
const selectionTones: Record<string, ChipTone> = { included: 'ok', excluded: 'bad', pending: 'warn' }

function describeEvent(event: ActivityEvent): { icon: ReactNode; text: string; chips: EventChip[] } {
  const p = event.payload as Record<string, string | number | null>
  const lucide = (Icon: LucideIcon, text: string, chips: EventChip[] = []) => ({ icon: <Icon size={15} aria-hidden />, text, chips })
  const brand = (id: string, text: string, chips: EventChip[] = []) => ({ icon: <ConnectionIcon id={id} />, text, chips })
  const reason = p.pause_reason ? [{ label: pauseReasonText(String(p.pause_reason)), tone: 'neutral' as const }] : []
  const errorChip = p.error_code ? [{ label: String(p.error_code), tone: 'neutral' as const }] : []
  switch (event.type) {
    case 'research_created': return lucide(FilePlus2, t('Research created'))
    case 'scope_revised': return lucide(PencilLine, t('Question revised (revision {n})', { n: String(p.scope_revision) }))
    case 'run_queued': return lucide(ListPlus, t(p.kind === 'discovery' ? 'Search run queued' : 'Answer run queued'))
    case 'run_started': return lucide(Play, t('Run started'))
    case 'run_completed': return lucide(CircleCheck, t('Run completed'), [statusChip('completed')])
    case 'run_paused': return lucide(Pause, t('Run paused'), reason)
    case 'run_failed': return lucide(CircleX, t('Run failed'), [statusChip('failed'), ...reason])
    case 'run_resumed': return lucide(RotateCw, t('Run resumed'))
    case 'run_cancelled': return lucide(Ban, t('Run cancelled'))
    case 'run_pause_requested': return lucide(Hand, t('Pause requested'))
    case 'step_started': return lucide(CircleDot, t('{step} started', { step: stepLabel(String(p.kind), String(p.operation_key)) }))
    case 'step_finished': return lucide(ListChecks, stepLabel(String(p.kind), String(p.operation_key)), [statusChip(p.status), ...errorChip])
    case 'model_call_started': return brand(String(p.connection), t('Model call sent to {connection}', { connection: String(p.connection) }), p.requested_model ? [{ label: String(p.requested_model), tone: 'neutral' }] : [])
    case 'search_recorded': return brand(String(p.provider), t('{provider} search', { provider: providerName(String(p.provider)) }), [statusChip(p.status), { label: t('{count} records', { count: String(p.result_count) }), tone: 'neutral' }])
    case 'pdf_discovery_recorded': return brand(String(p.provider), t('{provider} PDF lookup', { provider: providerName(String(p.provider)) }), [statusChip(p.status), { label: t('{count} candidates', { count: String(p.result_count) }), tone: 'neutral' }, ...errorChip])
    case 'asset_removed': return lucide(Trash2, t('PDF removed from a source'))
    case 'selection_changed': return lucide(UserPen, t('You marked a source'), [{ label: t(selectionStates[String(p.state)] ?? String(p.state)), tone: selectionTones[String(p.state)] ?? 'neutral' }])
    case 'answer_saved': return lucide(MessageSquareQuote, t('Answer saved'), [statusChip(p.status)])
    default: return lucide(Activity, event.type)
  }
}
