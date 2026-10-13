import { useCallback, useEffect, useRef, useState } from 'react'
import { CircleX, Lightbulb, Plus, RotateCw } from 'lucide-react'
import { api, type CandidateCard, type CandidateListItem, type ResearchView } from '../api'
import type { ModelText } from '../modelText'
import { StackPanel } from '../research/SplitPanel'
import { t } from '../i18n'
import { CandidateDetail } from './CandidateDetail'
import { errorText, kindLabels, label, statusLabels } from './labels'
import { useReturnFocus } from './focus'
import '../research/kit.css'
import './candidate.css'

export type CandidateSelection = { id: string; card?: CandidateCard }

// The Candidates panel (mockup `candList`, P35): one card per claim the person wants to test, with where it came from,
// its version, the status code computed and the person's own decision. A card opens its candidate stacked on this list.
export function CandidatesView({ researchId, view, dark, modelText, selection, onCount, onRunChanged, onOpenSource }: {
  researchId: string; view: ResearchView; dark: boolean; modelText: ModelText; selection: CandidateSelection | null
  onCount: (n: number) => void; onRunChanged: () => void; onOpenSource?: (sourceVersionId: string) => void
}) {
  const [items, setItems] = useState<CandidateListItem[] | null>(null)
  const [origins, setOrigins] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<CandidateSelection | null>(selection)
  const [seenSelection, setSeenSelection] = useState(selection)
  if (selection !== seenSelection) { setSeenSelection(selection); if (selection) setSelected(selection) }
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const addControl = useRef<HTMLButtonElement>(null)
  const addFocus = useReturnFocus()
  const closeAdd = () => { setAdding(false); addFocus.restoreFocus() }
  const onCountRef = useRef(onCount)
  useEffect(() => { onCountRef.current = onCount }, [onCount])
  const load = useCallback(() => {
    const request = ++generation.current
    return api.candidates(researchId).then(async fresh => {
      if (request !== generation.current) return
      setItems(fresh); setError(''); onCountRef.current(fresh.filter(c => !c.trashed_at).length)
      const cards = await Promise.allSettled(fresh.filter(c => !c.claim_statement).map(async item => ({ id: item.id, card: await api.candidate(researchId, item.id) })))
      if (request !== generation.current) return
      const loaded: Record<string, string> = {}
      cards.forEach(result => { if (result.status === 'fulfilled') loaded[result.value.id] = result.value.card.origin_text; else setError(errorText(result.reason)) })
      setOrigins(loaded)
    }).catch(e => { if (request === generation.current) setError(errorText(e)) })
  }, [researchId])
  const invalidate = useCallback(() => { generation.current++ }, [])
  useEffect(() => { void load(); return invalidate }, [load, invalidate, view.last_event_id])
  const applyCard = useCallback((card: CandidateCard) => {
    generation.current++
    const current = card.versions.find(v => v.id === card.current_version_id)
    const item: CandidateListItem = { id: card.id, origin: card.origin, origin_report_id: card.origin_report_id, origin_gap_row_id: card.origin_gap_row_id, gap_kind: card.gap_kind,
      origin_changed: card.origin_changed, current_version: card.current_version, trashed_at: card.trashed_at, claim_statement: current?.claim_statement ?? null, status: card.status?.computed ?? null, owner: card.status?.owner ?? null, active_run_id: card.active_run?.id ?? null }
    setItems(items => items?.some(i => i.id === card.id) ? items.map(i => i.id === card.id ? item : i) : [...(items ?? []), item])
    setOrigins(values => ({ ...values, [card.id]: card.origin_text }))
    void load()
  }, [load])
  async function save() {
    if (!text.length || busy) return
    generation.current++; setBusy(true); setFieldError('')
    try { const card = await api.openCandidate(researchId, { origin: 'owner_text', text }); applyCard(card); setAdding(false); setText(''); setSelected({ id: card.id, card }) }
    catch (e) { setFieldError(errorText(e)) }
    finally { setBusy(false) }
  }
  // Back (or Close) clears the candidate; the panel stack hands focus back to the card that opened it.
  const closeDetail = useCallback(() => setSelected(null), [])
  const origin = selected ? selected.card?.origin ?? items?.find(i => i.id === selected.id)?.origin : undefined
  const detailTitle = origin === 'report_gap' ? t('Candidates · From a report row') : origin === 'owner_text' ? t('Candidates · Your sentence') : t('Candidate')
  return <div className="candidates-view candidates-list mk pad">
    <p>{t('A candidate is one claim you want to test against the literature. Nothing is searched until you start a search on a card.')}</p>
    {adding ? <form className="ceditor candidate-form candidate-add" onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeAdd() } }} onSubmit={e => { e.preventDefault(); void save() }}>
      <label className="lbl">{t('Your sentence')}<textarea className="field" required autoFocus rows={2} maxLength={2000} value={text} placeholder={t('One claim you want to test, in your own words.')} aria-describedby="candidate-add-count" onChange={e => setText(e.target.value)} /><small id="candidate-add-count">{t('{n}/{max} characters', { n: text.length, max: 2000 })}</small></label>
      <p className="foot-note">{t('Your sentence is stored with surrounding whitespace removed. It is your proposal, not a finding from the literature.')}</p>
      {fieldError && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{fieldError}</span></div>}
      <div className="acts"><button type="submit" className="btn-pri" disabled={busy || !text.length} aria-describedby={busy || !text.length ? 'candidate-add-reason' : undefined}>{t('Save')}</button><button type="button" className="ghost" onClick={closeAdd}>{t('Cancel')}</button>{(busy || !text.length) && <span id="candidate-add-reason" className="foot-note">{t(busy ? 'Saving…' : 'Enter a sentence to save.')}</span>}</div>
    </form> : <div className="acts">
      <button ref={addControl} type="button" className="ghost" onClick={e => { addFocus.rememberFocus(e.currentTarget, () => addControl.current); setAdding(true) }}><Plus aria-hidden />{t('Add candidate')}</button>
      <button type="button" className="ghost" onClick={() => void load()}><RotateCw aria-hidden />{t('Refresh')}</button>
    </div>}
    {error && <div className="notice bad" role="alert"><CircleX aria-hidden /><div className="nb"><span>{error}</span><div className="acts"><button type="button" className="ghost" onClick={() => void load()}>{t('Retry')}</button></div></div></div>}
    {!items ? !error && <p role="status" className="foot-note">{t('Loading candidates…')}</p> : !items.length ? <p className="foot-note">{t('No candidates yet. Use Add candidate to store a claim you want to test.')}</p>
      : <ul className="candidate-list" aria-label={t('Candidates')}>{items.map(item => {
        const meta = <span className="meta">{item.origin === 'owner_text' ? t('Your sentence') : t('From a report row: {kind}', { kind: label(kindLabels, item.gap_kind ?? '') })}{item.current_version ? <> · {t('Version {n}', { n: item.current_version })}</> : null}<span className="spacer" />
          <span className={`cst ${item.status?.status ?? 'not_run'}`}>{label(statusLabels, item.status?.status ?? 'not_run')}</span>{item.owner && <span className={`cst yours ${item.owner.status}`}>{t('You: {status}', { status: label(statusLabels, item.owner.status) })}</span>}</span>
        const claim = <p className="candidate-list-claim" data-stored-text>{item.claim_statement ?? origins[item.id] ?? t('Loading…')}</p>
        return <li key={item.id}>{item.trashed_at ? <div className="ccard is-trashed">{meta}{claim}<span className="meta">{t('In the Trash')}</span></div>
          : <button type="button" className="ccard candidate-list-row" onClick={() => setSelected({ id: item.id })}>{meta}{claim}
            <span className="meta">{item.current_version ? t('Card written') : t('No card yet')}{item.active_run_id && <> · <span className="spin" aria-hidden /> {t('Search running')}</>}</span></button>}</li>
      })}</ul>}
    {selected && <StackPanel name="cand" open onClose={closeDetail} title={detailTitle} icon={Lightbulb} className={`mk-detail-box cand-panel-box${dark ? ' dark' : ''}`}>
      <CandidateDetail key={selected.id} researchId={researchId} candidateId={selected.id} initialCard={selected.card} view={view} dark={dark} modelText={modelText} onCard={applyCard} onRefreshList={load} onRunChanged={onRunChanged} onOpenSource={onOpenSource} />
    </StackPanel>}
  </div>
}
