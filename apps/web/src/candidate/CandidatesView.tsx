import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type CandidateCard, type CandidateListItem, type ResearchView } from '../api'
import { Notice } from '../Notice'
import type { ModelText } from '../modelText'
import { t } from '../i18n'
import { CandidateDetail } from './CandidateDetail'
import { errorText, kindLabels, label, statusLabels } from './labels'
import { useReturnFocus } from './focus'
import './candidate.css'

export type CandidateSelection = { id: string; card?: CandidateCard }
export function CandidatesView({ researchId, view, dark, modelText, selection, onCount, onRunChanged }: {
  researchId: string; view: ResearchView; dark: boolean; modelText: ModelText; selection: CandidateSelection | null
  onCount: (n: number) => void; onRunChanged: () => void
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
  const rows = useRef(new Map<string, HTMLButtonElement>())
  const invokingRow = useRef<string | null>(null)
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
    try { const card = await api.openCandidate(researchId, { origin: 'owner_text', text }); applyCard(card); setAdding(false); setText(''); invokingRow.current = null; setSelected({ id: card.id, card }) }
    catch (e) { setFieldError(errorText(e)) }
    finally { setBusy(false) }
  }
  const back = () => { const id = invokingRow.current; setSelected(null); requestAnimationFrame(() => (id ? rows.current.get(id) : addControl.current)?.focus()) }
  return <div className="candidates-view">
    {selected ? <CandidateDetail key={selected.id} researchId={researchId} candidateId={selected.id} initialCard={selected.card} view={view} dark={dark} modelText={modelText} onBack={back} onCard={applyCard} onRefreshList={load} onRunChanged={onRunChanged} /> : <>
      <h2>{t('Candidates')}</h2><p>{t('A candidate is one claim you want to test against the literature. Nothing is searched until you start a search on a card.')}</p>
      <div className="candidate-actions"><Button ref={addControl} onClick={e => { addFocus.rememberFocus(e.currentTarget, () => addControl.current); setAdding(true) }}>{t('Add candidate')}</Button><Button variant="ghost" onClick={() => void load()}>{t('Refresh')}</Button></div>
      {adding && <form className="candidate-form candidate-add" onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); closeAdd() } }} onSubmit={e => { e.preventDefault(); void save() }}><label className="evidence-field"><span>{t('Your sentence')}</span><small>{t('{n}/{max} characters', { n: text.length, max: 2000 })}</small><textarea required autoFocus rows={4} maxLength={2000} value={text} onChange={e => setText(e.target.value)} /></label>
        <p>{t('Your sentence is stored with surrounding whitespace removed. It is your proposal, not a finding from the literature.')}</p>{fieldError && <Notice tone="error">{fieldError}</Notice>}
        <div className="candidate-actions"><Button type="submit" disabled={busy || !text.length} aria-describedby="candidate-add-reason">{t('Save')}</Button><Button type="button" variant="outline" onClick={closeAdd}>{t('Cancel')}</Button></div>{(busy || !text.length) && <p id="candidate-add-reason">{t(busy ? 'Saving…' : 'Enter a sentence to save.')}</p>}
      </form>}
      {error && <Notice tone="error">{error}<Button variant="ghost" onClick={() => void load()}>{t('Retry')}</Button></Notice>}
      {!items ? !error && <p role="status">{t('Loading candidates…')}</p> : !items.length ? <p className="candidate-fine">{t('No candidates yet. Use Add candidate to store a claim you want to test.')}</p> : <ul className="candidate-list">{items.map(item => <li key={item.id}>
        {item.trashed_at ? <><p className="candidate-claim" data-stored-text>{item.claim_statement ?? origins[item.id]}</p><p>{t('In the Trash')}</p></> : <button type="button" className="candidate-list-row" ref={el => { if (el) rows.current.set(item.id, el); else rows.current.delete(item.id) }} onClick={() => { invokingRow.current = item.id; setSelected({ id: item.id }) }}>
          <span className="candidate-claim candidate-list-claim" data-stored-text>{item.claim_statement ?? origins[item.id] ?? t('Loading…')}</span>
          <span>{item.origin === 'owner_text' ? t('Your proposal') : t('From a report row: {kind}', { kind: label(kindLabels, item.gap_kind ?? '') })}</span>
          <span>{item.current_version ? t('Version {n}', { n: item.current_version }) : t('No card yet')} · {label(statusLabels, item.status?.status ?? 'not_run')}{item.owner && <> · {t('You: {status}', { status: label(statusLabels, item.owner.status).toLocaleLowerCase() })}</>}</span>
          {item.active_run_id && <span>{t('Search running')}</span>}
        </button>}
      </li>)}</ul>}
    </>}
  </div>
}
