import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { api, ApiError, type LineageBaseline, type LineageLink, type LineagePlan, type LineageStepOutcome, type LineageView, type Run, type Source } from '../api'
import { ConfirmDialog } from '../ConfirmDialog'
import { ModelName } from '../ModelName'
import { Notice } from '../Notice'
import { useToast } from '../Toast'
import { t } from '../i18n'
import { runStatusLabels } from '../labels'
import { LinkRow, WorkName, type PassageTarget, type WorkProps } from './LinkRow'
import { LinkEditor, type EditorTarget } from './LinkEditor'
import { BaselinePanel } from './BaselinePanel'
import { authorText, currencyText, dateText, decisionLabels, edgeLabels, outcomeLabels, reasonLabels, rejectionLabels, relationLabels, supportText, workText } from './labels'

const errorText = (e: unknown) => e instanceof Error ? e.message : String(e)
function ListSection({ title, count, children, empty }: { title: string; count: number; children: ReactNode; empty?: boolean }) {
  return <section className="lineage-section" aria-label={t(title)}><h3>{t(title)} · {count}</h3>{empty ? <p>{t('None.')}</p> : children}</section>
}
function Outcomes({ title, items, ...work }: WorkProps & { title: string; items: LineageStepOutcome[] }) {
  return <ListSection title={title} count={items.length} empty={!items.length}><ul>{items.map((item, i) => <li key={`${item.run_id}:${item.key}:${i}`}>
    <p>{t(outcomeLabels[item.kind])}</p><p>{item.from && <><WorkName id={item.from} {...work} /> <span aria-hidden> → </span></>}<WorkName id={item.to} {...work} /></p>
    {item.reason && <p className="lineage-stored" data-stored-text>{item.reason}</p>}
    <p>{t('run {id}', { id: item.run_id })} · {dateText(item.recorded_at)} · {t('scope revision {n}', { n: item.scope_revision })}</p>
    <p className="lineage-currency">{currencyText(item)}</p>
  </li>)}</ul></ListSection>
}
export function DevelopmentLines({ researchId, tableId, tableVersion, eventCursor, activeRun, lineageRun, sources, model, connection, dark, onColumnsAdded, onRunStarted, onPassage }: {
  researchId: string; tableId: string; tableVersion: number; eventCursor: number; activeRun: Run | null; lineageRun: Run | undefined
  sources: Source[]; model: string; connection: string; dark: boolean; onColumnsAdded: () => void; onRunStarted: () => void
  onPassage: (target: PassageTarget) => void
}) {
  const toast = useToast()
  const [view, setView] = useState<LineageView | null>(null)
  const [error, setError] = useState('')
  const [baselineOpen, setBaselineOpen] = useState(false)
  const [baseline, setBaseline] = useState<LineageBaseline | null>(null)
  const [baselineError, setBaselineError] = useState('')
  const [planOpen, setPlanOpen] = useState(false)
  const [plan, setPlan] = useState<LineagePlan | null>(null)
  const [planError, setPlanError] = useState('')
  const [retry, setRetry] = useState(false)
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState<EditorTarget | null>(null)
  const [removing, setRemoving] = useState<LineageLink | null>(null)
  const [removeNote, setRemoveNote] = useState('')
  const returnFocus = useRef<HTMLElement | null>(null)
  const generation = useRef(0)
  const appliedRequest = useRef(0)
  const currentView = useRef<LineageView | null>(null)
  const pendingRead = useRef<Promise<LineageView> | null>(null)
  const baselineGeneration = useRef(0)
  const planGeneration = useRef(0)
  const beginMutation = useCallback(() => ++generation.current, [])
  const invalidate = useCallback(() => { generation.current++ }, [])
  const invalidatePlan = useCallback(() => { planGeneration.current++ }, [])
  const invalidateBaseline = useCallback(() => { baselineGeneration.current++ }, [])
  const load = useCallback(() => {
    const request = ++generation.current
    const response: Promise<LineageView> = api.lineage(researchId, tableId).then(fresh => {
      if (request === generation.current && request >= appliedRequest.current) { appliedRequest.current = request; currentView.current = fresh; setView(fresh); setError('') }
      // Dialog reloads must also receive the newer read, rather than its superseded response.
      else if (pendingRead.current && pendingRead.current !== response) return pendingRead.current
      return currentView.current ?? fresh
    }, e => { if (generation.current === request) setError(errorText(e)); throw e })
    pendingRead.current = response
    return response
  }, [researchId, tableId])
  // Event cursor covers writes that don't change the table version. No independent polling.
  useEffect(() => {
    void load().catch(() => {})
    return invalidate
  }, [load, invalidate, tableVersion, eventCursor, lineageRun?.id, lineageRun?.status])
  const loadBaseline = useCallback(() => {
    const request = ++baselineGeneration.current
    return api.lineageBaseline(researchId, tableId).then(
      fresh => { if (request === baselineGeneration.current) { setBaseline(fresh); setBaselineError('') } },
      e => { if (request === baselineGeneration.current) setBaselineError(errorText(e)) },
    )
  }, [researchId, tableId])
  useEffect(() => {
    if (!baselineOpen) return
    void loadBaseline()
    return invalidateBaseline
  }, [baselineOpen, loadBaseline, invalidateBaseline, tableVersion, eventCursor])
  const loadPlan = useCallback(() => {
    const request = ++planGeneration.current
    return api.lineagePlan(researchId, tableId, retry).then(
      fresh => { if (request === planGeneration.current) { setPlan(fresh); setPlanError('') } },
      e => { if (request === planGeneration.current) setPlanError(errorText(e)) },
    )
  }, [researchId, tableId, retry])
  useEffect(() => {
    if (!planOpen) return
    void loadPlan()
    return invalidatePlan
  }, [planOpen, loadPlan, invalidatePlan])
  const applyMutation = (fresh: LineageView, request: number) => {
    // A later applied read owns the view; refetch after the write rather than publish its older snapshot.
    if (request < appliedRequest.current) { void load().catch(() => {}); return }
    appliedRequest.current = request; currentView.current = fresh; setView(fresh); setError('')
    // A read that started during the write may carry the pre-write state: a fresh read supersedes it.
    if (generation.current !== request) void load().catch(() => {})
  }
  const replaceView = (fresh: LineageView, request: number) => {
    applyMutation(fresh, request); toast('success', t('Development link saved. The quote was located in the later work’s text.'))
  }
  async function refresh() { await load().catch(() => {}); if (baselineOpen) await loadBaseline(); if (planOpen) await loadPlan() }
  const rememberFocus = () => { returnFocus.current = document.activeElement as HTMLElement | null }
  const openEditor = (target: EditorTarget) => { rememberFocus(); setEditor(target) }
  const closeEditor = () => setEditor(null)
  async function start() {
    if (!plan || !plan.selected.length) return
    setBusy(true)
    try { await api.startLineageRun(researchId, tableId, plan.preview_fingerprint, retry, crypto.randomUUID()); setPlanOpen(false); onRunStarted() }
    catch (e) { setPlanError(errorText(e)); toast(e instanceof ApiError && e.status === 409 ? 'warning' : 'error', errorText(e)); if (e instanceof ApiError && e.status === 409) await loadPlan() }
    finally { setBusy(false) }
  }
  async function remove() {
    if (!removing) return
    const request = beginMutation()
    setBusy(true)
    try {
      const fresh = await api.removeLineageLink(researchId, tableId, removing.link_id, { expected_version: removing.version, based_on_revision_id: removing.revision_id, note: removeNote || null }, crypto.randomUUID())
      applyMutation(fresh, request); setRemoving(null); toast('success', t('Development link removed. The human decision is kept.'))
    } catch (e) {
      toast(e instanceof ApiError && e.status === 409 ? 'warning' : 'error', errorText(e))
      if (e instanceof ApiError && e.status === 409) {
        try {
          const fresh = await load()
          const link = [...fresh.components.flatMap(c => c.links), ...fresh.cross_relations, ...fresh.history.stale, ...fresh.history.out_of_scope].find(l => l.link_id === removing.link_id)
          setRemoving(link ?? null)
          if (!link) toast('warning', t('This pair changed; reopen'))
        } catch { setRemoving(null); toast('warning', t('This pair changed; reopen')) }
      }
    }
    finally { setBusy(false) }
  }
  const missing = view ? Object.entries(view.status.roles).filter(([, present]) => !present).map(([role]) => t({ problem: 'Problem', change: 'Change', uncertainty: 'Uncertainty' }[role]!)) : []
  const reason = missing.length ? t('Add the missing development columns first.') : activeRun ? t('Available when the active run finishes') : ''
  const work: WorkProps = { nodes: view?.nodes ?? {}, onPassage }
  const linkRow = (link: LineageLink, component?: LineageView['components'][number]) => <LinkRow key={link.link_id} link={link} component={component} {...work}
    onEdit={link => openEditor({ link })} onRemove={link => { rememberFocus(); setRemoveNote(''); setRemoving(link) }} />
  if (!view) return <div className="lineage-view">{error ? <Notice tone="error">{error}<Button variant="ghost" onClick={() => void refresh()}>{t('Retry')}</Button></Notice> : <p role="status">{t('Loading development lines…')}</p>}</div>
  const s = view.status, counts = view.counts
  return <div className="lineage-view" role="tabpanel" id={`lineage-panel-${tableId}`} aria-label={t('Development lines')}>
    {error && <Notice tone="error">{error}<Button variant="ghost" onClick={() => void refresh()}>{t('Retry')}</Button></Notice>}
    <section className="lineage-status" aria-label={t('Development status')}>
      <h3>{t('Development status')}</h3>
      <p>{missing.length ? t('Problem, change and uncertainty columns: missing: {roles}', { roles: missing.join(', ') }) : t('Problem, change and uncertainty columns: present')}</p>
      <p>{t('{live} live rows · {pdf} rows with stored PDF text · {complete} complete nodes · {partial} partial nodes · {missing} missing cells', { live: s.live_rows, pdf: s.pdf_text_rows, complete: s.nodes_complete, partial: s.nodes_partial, missing: s.missing_cells })}</p>
      <p>{t('{placed} placed rows · {unplaced} unplaced rows', { placed: s.placed_rows, unplaced: s.unplaced_rows })}</p>
      <div className="lineage-actions lineage-toolbar">
        {missing.length > 0 && <Button variant="ghost" disabled={busy} onClick={async () => { setBusy(true); try { await api.addDevelopmentColumns(researchId, tableId, tableVersion, crypto.randomUUID()); toast('success', t('Development columns added.')); onColumnsAdded(); await load() } catch (e) { toast('error', errorText(e)) } finally { setBusy(false) } }}>{t('Add development columns')}</Button>}
        <Button disabled={busy || Boolean(reason)} aria-describedby={reason ? 'lineage-find-reason' : undefined} onClick={() => { setPlan(null); setPlanError(''); if (planOpen) void loadPlan(); else setPlanOpen(true) }}>{t('Find development links')}</Button>
        <label className="evidence-check"><input type="checkbox" checked={retry} onChange={e => { setPlan(null); setPlanError(''); setRetry(e.target.checked) }} />{t('Retry failed pairs')}</label>
        <Button variant="ghost" onClick={() => openEditor({})}>{t('Add link')}</Button>
        <Button variant="ghost" aria-expanded={baselineOpen} aria-controls="lineage-baseline-panel" onClick={() => setBaselineOpen(v => !v)}>{t('Field baseline')}</Button>
        <Button variant="ghost" onClick={() => void refresh()}>{t('Refresh')}</Button>
      </div>
      {reason && <p id="lineage-find-reason">{reason}</p>}
      {lineageRun && (['queued', 'running', 'pause_requested', 'paused'].includes(lineageRun.status)) && <p role="status">{t('Development links')} · {t(runStatusLabels[lineageRun.status])}</p>}
      {planOpen && <div className="lineage-plan" aria-label={t('Development link plan')}>
        <h4>{t('Development link plan')}</h4>
        {planError && <Notice tone="error">{planError}<Button variant="ghost" onClick={() => void loadPlan()}>{t('Retry')}</Button></Notice>}
        {!plan && !planError && <p role="status">{t('Loading the plan…')}</p>}
        {plan && <><p>{t('{n} works will be read', { n: plan.selected.length })} · {plan.calls === 0 ? t('0 model calls; the scan is recorded') : t('{n} model calls', { n: plan.calls })} · {t('at most {n} model calls', { n: plan.max_model_calls })}</p>
          <p><ModelName connection={connection} text={model} /></p>
          <h4>{t('Selected works')} · {plan.selected.length}</h4>{plan.selected.length ? <ul>{plan.selected.map(item => <li key={item.to}><WorkName id={item.to} {...work} /> · {t(item.class)} · {t('{n} candidates', { n: item.candidate_count })} · {t('{n} model calls', { n: item.chunk_count })}{item.no_candidate && <> · {t(reasonLabels.no_candidate)}</>}</li>)}</ul> : <p>{t('No targets are selected; there is nothing to assess.')}</p>}
          <h4>{t('Unselected targets')} · {plan.not_selected.length}</h4>{plan.not_selected.length ? <ul>{plan.not_selected.map(item => <li key={item.to}><WorkName id={item.to} {...work} /> · {t(item.reason === 'settled' ? 'unchanged recorded outcome' : 'beyond the work limit')}</li>)}</ul> : <p>{t('None.')}</p>}
          <h4>{t('Pairs not sent for budget')} · {plan.not_sent_budget.length}</h4>{plan.not_sent_budget.length ? <ul>{plan.not_sent_budget.map((item, i) => <li key={i}><WorkName id={item.from} {...work} /> → <WorkName id={item.to} {...work} /> · {item.reason}</li>)}</ul> : <p>{t('None.')}</p>}
          <h4>{t('Unchanged failed pairs')} · {plan.failed_unchanged.length}</h4>{plan.failed_unchanged.length ? <ul>{plan.failed_unchanged.map((item, i) => <li key={i}><WorkName id={item.from} {...work} /> → <WorkName id={item.to} {...work} /></li>)}</ul> : <p>{t('None.')}</p>}
        </>}
        <div className="lineage-actions"><Button disabled={busy || !plan || plan.selected.length === 0} onClick={() => void start()}>{t('Start')}</Button><Button variant="outline" onClick={() => setPlanOpen(false)}>{t('Cancel')}</Button></div>
      </div>}
      <p className="lineage-limit">{t('Links are model proposals or human decisions, each recorded with text quoted from the later work. Whether the quoted text supports the relation has not been checked.')}</p>
    </section>
    <ListSection title="Lines" count={view.components.length} empty={!view.components.length}>{view.components.map(c => <section key={c.id} className="lineage-component">
      <h4>{t('Line · {n} members', { n: c.members.length })}</h4>
      <p>{t('Year order')}</p>{c.roots.length > 0 && <p>{t('starts at {works}', { works: c.roots.map(id => workText(view.nodes[id])).join(', ') })}</p>}
      {c.branches.length > 0 && <p>{t('branches at {works}', { works: c.branches.map(id => workText(view.nodes[id])).join(', ') })}</p>}{c.merges.length > 0 && <p>{t('merges at {works}', { works: c.merges.map(id => workText(view.nodes[id])).join(', ') })}</p>}
      {c.has_cycle && <Notice tone="error">{t('contains a cycle among stored links')}</Notice>}
      <ol>{c.links.map(link => linkRow(link, c))}</ol>
    </section>)}</ListSection>
    <ListSection title="Independent parallel work" count={view.cross_relations.length}><p>{t('stated by the later work as parallel; these do not form lines')}</p>{view.cross_relations.length ? <ul>{view.cross_relations.map(link => linkRow(link))}</ul> : <p>{t('None.')}</p>}</ListSection>
    <ListSection title="Works without a placed link" count={view.unplaceable.length} empty={!view.unplaceable.length}><ul>{view.unplaceable.map(item => <li key={item.source_version_id}>
      <WorkName id={item.source_version_id} {...work} /><ul>{item.reasons.map(r => <li key={r}>{t(reasonLabels[r])}</li>)}</ul>
      {item.last_run && <p>{t('last considered in run of {date}', { date: dateText(item.last_run.recorded_at) })}</p>}
      <details><summary>{t('Recorded details · {n}', { n: item.details.length })}</summary>{item.details.length ? <ul>{item.details.map((detail, i) => <li key={i}>
        <p>{t(reasonLabels[detail.reason])}</p><p>{detail.from && <WorkName id={detail.from} {...work} />}{detail.from && detail.to && ' → '}{detail.to && <WorkName id={detail.to} {...work} />}</p>
        <p>{detail.run_id && t('run {id}', { id: detail.run_id })}{detail.scope_revision != null && <> · {t('scope revision {n}', { n: detail.scope_revision })}</>}{detail.recorded_at && <> · {dateText(detail.recorded_at)}</>}</p><p className="lineage-currency">{currencyText(detail)}</p>
      </li>)}</ul> : <p>{t('None.')}</p>}</details>
      <div className="lineage-actions"><Button variant="ghost" size="sm" onClick={() => openEditor({ to: item.source_version_id })}>{t('Add a link as later work')}</Button><Button variant="ghost" size="sm" onClick={() => openEditor({ from: item.source_version_id })}>{t('Add a link as earlier work')}</Button></div>
    </li>)}</ul></ListSection>
    <ListSection title="Proposals not accepted" count={view.not_accepted.length} empty={!view.not_accepted.length}><ul>{view.not_accepted.map(item => <li key={item.revision_id}>
      <p><WorkName id={item.from} {...work} /> → <WorkName id={item.to} {...work} /></p><p>{t(rejectionLabels[item.rejection_code] ?? item.rejection_code)}</p>
      <p>{t(decisionLabels[item.decision])}{item.relation && <> · {t(relationLabels[item.relation])}</>}{item.support_type && <> · {supportText(item.support_type)}</>}</p>
      {item.what_changed != null && <p data-stored-text className="lineage-stored">{item.what_changed}</p>}{item.note != null && <p data-stored-text className="lineage-stored">{item.note}</p>}
      {item.superseded && <p>{t('a later decision exists on this pair')}</p>}<p>{t('Recorded pair decision: {decision}', { decision: t(decisionLabels[item.pair_state.decision]) })}{item.pair_state.author && <> · {authorText(item.pair_state.author)}</>}</p>
      <p>{t('run {id}', { id: item.run_id })} · {dateText(item.created_at)}</p>
    </li>)}</ul></ListSection>
    <ListSection title="Citation edges without a mention" count={view.unassessed_edges.length}><p>{t('The stored reference list of the later work names the earlier one, but no mention was found in its scanned text.')}</p>{view.unassessed_edges.length ? <ul>{view.unassessed_edges.map((pair, i) => <li key={i}><WorkName id={pair.from} {...work} /> → <WorkName id={pair.to} {...work} /></li>)}</ul> : <p>{t('None.')}</p>}</ListSection>
    <ListSection title="Citation edges into unscanned works" count={view.edges_into_unscanned_targets.length}><p>{t('The later work was not scanned for mentions; no mention claim is made.')}</p>{view.edges_into_unscanned_targets.length ? <ul>{view.edges_into_unscanned_targets.map((pair, i) => <li key={i}><WorkName id={pair.from} {...work} /> → <WorkName id={pair.to} {...work} /> · {t(pair.to_reason === 'no_pdf_text' ? 'has no stored PDF text' : 'has not been through a run')}</li>)}</ul> : <p>{t('None.')}</p>}</ListSection>
    <p>{t('An outcome may also appear in the budget or failed-pair list.')}</p>
    <Outcomes title="Pairs not sent for budget" items={view.not_sent_budget} {...work} /><Outcomes title="Failed pairs" items={view.failed_pairs} {...work} /><Outcomes title="Run outcomes" items={view.step_outcomes} {...work} />
    <section className="lineage-section"><h3>{t('History')}</h3>
      <details><summary>{t('Links that no longer hold because their inputs changed')} · {view.history.stale.length}</summary>{view.history.stale.length ? <ul>{view.history.stale.map(link => linkRow(link))}</ul> : <p>{t('None.')}</p>}</details>
      <details><summary>{t('Links whose work left this table or the selection')} · {view.history.out_of_scope.length}</summary>{view.history.out_of_scope.length ? <ul>{view.history.out_of_scope.map(link => linkRow(link))}</ul> : <p>{t('None.')}</p>}</details>
    </section>
    {baselineOpen && <div id="lineage-baseline-panel">{baselineError ? <Notice tone="error">{baselineError}<Button variant="ghost" onClick={() => void loadBaseline()}>{t('Retry')}</Button></Notice> : baseline ? <BaselinePanel baseline={baseline} {...work} /> : <p role="status">{t('Loading field baseline…')}</p>}</div>}
    <section className="lineage-section lineage-counts"><h3>{t('Counts')}</h3>
      <p>{t('{components} components · {links} current links · {cross} cross relations · {stale} stale · {out} out of scope · {rejected} not accepted · {unplaced} unplaced · {edges} edges without mention', { components: counts.components, links: counts.current_links, cross: counts.cross_relations, stale: counts.history_stale, out: counts.history_out_of_scope, rejected: counts.not_accepted, unplaced: counts.unplaceable.total, edges: counts.unassessed_edges })}</p>
      <p>{t('Citation lists')} · {Object.entries(counts.edge_states).map(([state, n]) => `${t(edgeLabels[state as keyof typeof edgeLabels])} ${n}`).join(', ')} · {t('These are citation-list states, not link counts.')}</p>
    </section>
    {editor && <LinkEditor key={editor.link?.link_id ?? 'add'} target={editor} view={view} sources={sources} researchId={researchId} tableId={tableId} dark={dark} returnFocus={returnFocus}
      onClose={closeEditor} onChanged={replaceView} onMutationStart={beginMutation} onReload={load} onEdit={link => setEditor({ link })} />}
    <ConfirmDialog open={Boolean(removing)} dark={dark} title={t('Remove development link?')} description={t('The human removal is recorded and later model runs do not restore this pair.')}
      context={removing ? `${workText(view.nodes[removing.from])} → ${workText(view.nodes[removing.to])}` : undefined}
      confirmLabel={t('Remove link')} cancelLabel={t('Keep link')} busy={busy} onConfirm={() => void remove()} onOpenChange={open => { if (!open) setRemoving(null) }}>
      {removing && <label className="evidence-field"><span>{t('Note (optional)')}</span><textarea value={removeNote} maxLength={2000} rows={2} onChange={e => setRemoveNote(e.target.value)} /></label>}
    </ConfirmDialog>
  </div>
}
