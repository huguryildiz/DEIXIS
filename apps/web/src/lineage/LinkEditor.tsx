import { useEffect, useRef, useState, type RefObject } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, ApiError, type AssetText, type LineageLink, type LineagePairDecision, type LineageRelation, type LineageSupport, type LineageView, type Source } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { authorText, decisionLabels, relationLabels, supportText, workText } from './labels'

export type EditorTarget = { link?: LineageLink; from?: string; to?: string }
export function LinkEditor({ target, view, sources, researchId, tableId, dark, returnFocus, onChanged, onMutationStart, onReload, onEdit, onClose }: {
  target: EditorTarget; view: LineageView; sources: Source[]; researchId: string; tableId: string; dark: boolean
  returnFocus: RefObject<HTMLElement | null>; onChanged: (view: LineageView, request: number) => void; onMutationStart: () => number; onReload: () => Promise<LineageView>
  onEdit: (link: LineageLink) => void; onClose: () => void
}) {
  const live = Object.values(view.nodes).filter(n => n.live)
  const [from, setFrom] = useState(target.link?.from ?? target.from ?? live[0]?.source_version_id ?? '')
  const [to, setTo] = useState(target.link?.to ?? target.to ?? live[1]?.source_version_id ?? live[0]?.source_version_id ?? '')
  const [relation, setRelation] = useState<LineageRelation>(target.link?.relation ?? 'extends')
  const [changed, setChanged] = useState(target.link?.what_changed ?? '')
  const [support, setSupport] = useState<LineageSupport>(target.link?.support_type ?? 'source_stated')
  const [note, setNote] = useState(target.link?.note ?? '')
  const [evidence, setEvidence] = useState(target.link?.evidence.map(e => ({ passage_id: e.passage_id, quote: e.anchor_text })) ?? [{ passage_id: '', quote: '' }])
  const [pair, setPair] = useState<LineagePairDecision | undefined>(() => view.pair_decisions.find(p => p.from === from && p.to === to))
  const [revision, setRevision] = useState(target.link?.revision_id)
  const [version, setVersion] = useState(target.link?.version ?? pair?.version ?? 0)
  const [textResult, setTextResult] = useState<{ view: LineageView; reload: number; to: string; assetId: string | undefined; value: AssetText | null; error: string } | null>(null)
  const [textReload, setTextReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const [conflicted, setConflicted] = useState(false)
  const passageBoxes = useRef<(HTMLDivElement | null)[]>([])
  const asset = sources.find(s => s.source_version_id === to)?.access.assets[0]
  const assetId = asset?.id
  const workId = view.nodes[to]?.work_id
  const textLoading = !textResult || textResult.view !== view || textResult.reload !== textReload || textResult.to !== to || textResult.assetId !== assetId
  const text = textLoading ? null : textResult.value
  const textError = textLoading ? '' : textResult.error
  useEffect(() => {
    let current = true
    const context = { view, reload: textReload, to, assetId }
    async function loadText() {
      if (assetId) return api.assetText(researchId, assetId)
      if (!workId) return null
      const work = await api.libraryWork(workId)
      const version = work.versions.find(v => v.source_version_id === to)
      const textResearch = version?.research_id ?? version?.removed_research_id
      return version?.asset && textResearch ? api.assetText(textResearch, version.asset.id) : null
    }
    loadText().then(value => { if (current) setTextResult({ ...context, value, error: '' }) }, e => { if (current) setTextResult({ ...context, value: null, error: e instanceof Error ? e.message : String(e) }) })
    return () => { current = false }
  }, [researchId, assetId, workId, to, view, textReload])
  // assetText is filtered by Store.passages_for; also check its source and PDF kind before offering evidence.
  const passages = text?.source.id === to && (!assetId || text.asset.id === assetId) ? text.passages.filter(p => p.kind === 'pdf_page') : []
  // Stored evidence is retained for editing; the server decides whether its passage is still usable.
  const storedEvidence = target.link?.evidence ?? []
  const selectable = (id: string) => passages.some(p => p.id === id) || storedEvidence.some(e => e.passage_id === id)
  const existing = !target.link && pair?.decision === 'link'
  const sameWork = Boolean(from && to && (from === to || view.nodes[from]?.work_id === view.nodes[to]?.work_id))
  const ready = !busy && !conflicted && !existing && !sameWork && from && to && changed.trim().length > 0 && changed.length <= 500
    && evidence.length >= 1 && evidence.length <= 5
    && evidence.every(e => e.quote.length > 0 && selectable(e.passage_id))
  function choosePair(nextFrom: string, nextTo: string) {
    setFrom(nextFrom); setTo(nextTo)
    const next = view.pair_decisions.find(p => p.from === nextFrom && p.to === nextTo)
    setPair(next); setVersion(next?.version ?? 0); setConflicted(false); setProblem('')
    if (nextTo !== to) setEvidence([{ passage_id: '', quote: '' }])
  }
  async function reload() {
    setBusy(true)
    try {
      const fresh = await onReload()
      const next = fresh.pair_decisions.find(p => p.from === from && p.to === to)
      setPair(next); setVersion(next?.version ?? 0); setRevision(next?.current_revision_id ?? undefined)
      setTextReload(n => n + 1)
      setConflicted(false); setProblem('')
    } catch (e) { setProblem(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function save() {
    if (!ready) return
    const request = onMutationStart()
    setBusy(true); setProblem('')
    const fields = { relation, what_changed: changed, support_type: support, note: note || null, evidence, expected_version: version }
    try {
      const fresh = target.link
        ? await api.editLineageLink(researchId, tableId, target.link.link_id, { ...fields, based_on_revision_id: revision! }, crypto.randomUUID())
        : await api.addLineageLink(researchId, tableId, { ...fields, from_source_version_id: from, to_source_version_id: to }, crypto.randomUUID())
      onChanged(fresh, request); onClose()
    } catch (e) {
      setConflicted(e instanceof ApiError && e.status === 409)
      setProblem(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  function updateEvidence(i: number, patch: Partial<typeof evidence[number]>) {
    setEvidence(items => items.map((item, index) => index === i ? { ...item, ...patch } : item))
  }
  function captureSelection(i: number) {
    const selection = window.getSelection()
    const box = passageBoxes.current[i]
    if (selection && box?.contains(selection.anchorNode) && box.contains(selection.focusNode)) updateEvidence(i, { quote: selection.toString() })
  }
  const findLink = () => [...view.components.flatMap(c => c.links), ...view.cross_relations, ...view.history.stale, ...view.history.out_of_scope].find(l => l.link_id === pair?.link_id)
  return <Sheet open onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet evidence-sheet lineage-editor ${dark ? 'dark' : ''}`} finalFocus={returnFocus}>
      <SheetHeader><SheetTitle>{t(target.link ? 'Edit development link' : 'Add development link')}</SheetTitle>
        <SheetDescription>{t('Choose text from the later work. Whether it supports the relation has not been checked.')}</SheetDescription></SheetHeader>
      <form className="sheet-body evidence-form lineage-form" id="lineage-link-form" onSubmit={e => { e.preventDefault(); void save() }}>
        <label className="evidence-field"><span>{t('Earlier work')}</span><select value={from} disabled={Boolean(target.link)} onChange={e => choosePair(e.target.value, to)}>
          {(target.link ? [view.nodes[from]] : live).filter(Boolean).map(n => <option key={n.source_version_id} value={n.source_version_id}>{workText(n)} · {n.title}</option>)}</select></label>
        <label className="evidence-field"><span>{t('Later work')}</span><select value={to} disabled={Boolean(target.link)} onChange={e => choosePair(from, e.target.value)}>
          {(target.link ? [view.nodes[to]] : live).filter(Boolean).map(n => <option key={n.source_version_id} value={n.source_version_id}>{workText(n)} · {n.title}</option>)}</select></label>
        {sameWork && <p>{t('Choose two different works.')}</p>}
        {existing && <p>{t('This pair already has a link; edit it instead')} <Button variant="ghost" type="button" onClick={() => { const link = findLink(); if (link) onEdit(link) }}>{t('Edit')}</Button></p>}
        {!existing && pair?.decision && <p>{t('Recorded pair decision: {decision}', { decision: t(decisionLabels[pair.decision]) })}{pair.author && <> · {authorText(pair.author)}</>}</p>}
        <label className="evidence-field"><span>{t('Relation')}</span><select value={relation} onChange={e => { const r = e.target.value as LineageRelation; setRelation(r); if (r === 'independent_parallel') setSupport('source_stated') }}>
          {Object.entries(relationLabels).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}</select></label>
        <label className="evidence-field"><span>{t('What changed')}</span><small>{t('{n}/500 characters', { n: changed.length })}</small><textarea value={changed} maxLength={500} rows={3} onChange={e => setChanged(e.target.value)} /></label>
        <label className="evidence-field"><span>{t('Support type')}</span><select value={support} onChange={e => setSupport(e.target.value as LineageSupport)}>
          <option value="source_stated">{supportText('source_stated')}</option><option value="analyst_inference" disabled={relation === 'independent_parallel'}>{supportText('analyst_inference')}</option></select></label>
        {relation === 'independent_parallel' && <p>{t('Independent parallel work requires source stated support.')}</p>}
        <label className="evidence-field"><span>{t('Note (optional)')}</span><textarea value={note} maxLength={2000} rows={2} onChange={e => setNote(e.target.value)} /></label>
        <h3>{t('Evidence')}</h3>
        {textError && <Notice tone="error">{textError}<Button type="button" variant="ghost" onClick={() => setTextReload(n => n + 1)}>{t('Retry')}</Button></Notice>}
        {textLoading ? <p role="status">{t('Loading PDF text…')}</p> : !passages.length && <p>{t('No PDF passages could be loaded for the later work.')}</p>}
        {!textLoading && !passages.length && !storedEvidence.length && <p>{t('Save is unavailable because no evidence passage can be selected. Your typed quotes are kept.')}</p>}
        {storedEvidence.length > 0 && <p>{t('You can keep the link’s stored evidence. The server will check it when you save.')}</p>}
        <ol className="lineage-evidence-picker">{evidence.map((item, i) => { const passage = passages.find(p => p.id === item.passage_id); return <li key={i}>
          <h4>{t('Evidence {i} of {n}', { i: i + 1, n: evidence.length })}</h4>
          <ul>{passages.map(p => <li key={p.id}><Button type="button" variant="ghost" aria-pressed={item.passage_id === p.id} onClick={() => updateEvidence(i, { passage_id: p.id })}>
            {p.physical_page != null ? t('PDF p. {page}', { page: p.physical_page }) : t('PDF passage')}{p.printed_label && <> · {p.printed_label}</>}</Button></li>)}</ul>
          {storedEvidence.map((e, index) => <Button key={`${e.passage_id}:${index}`} type="button" variant="ghost" aria-pressed={item.passage_id === e.passage_id} onClick={() => updateEvidence(i, { passage_id: e.passage_id, quote: e.anchor_text })}>{t('Keep stored evidence {n}', { n: index + 1 })}</Button>)}
          {passage && <><div className="lineage-passage-text" data-stored-text ref={el => { passageBoxes.current[i] = el }}>{passage.text}</div>
            <Button type="button" variant="ghost" onMouseDown={e => e.preventDefault()} onClick={() => captureSelection(i)}>{t('Use selected text')}</Button></>}
          <label className="evidence-field"><span>{t('Quote {n}', { n: i + 1 })}</span><textarea rows={3} value={item.quote} onChange={e => updateEvidence(i, { quote: e.target.value })} /></label>
          {evidence.length > 1 && <Button type="button" variant="ghost" onClick={() => setEvidence(items => items.filter((_, index) => index !== i))}>{t('Remove evidence {n}', { n: i + 1 })}</Button>}
        </li> })}</ol>
        <Button type="button" variant="outline" disabled={evidence.length >= 5} onClick={() => setEvidence(items => [...items, { passage_id: '', quote: '' }])}>{t('Add evidence item')}</Button>
        {evidence.length >= 5 && <p>{t('At most five evidence items.')}</p>}
        {problem && <Notice tone="error">{conflicted && <>{t('This pair changed since you opened it')} · </>}{problem}
          {conflicted && <Button type="button" variant="ghost" disabled={busy} onClick={() => void reload()}>{t('Reload')}</Button>}</Notice>}
      </form>
      <footer className="cell-foot"><div className="lineage-actions"><Button type="submit" form="lineage-link-form" disabled={!ready}>{t('Save link')}</Button><Button variant="outline" onClick={onClose}>{t('Cancel')}</Button></div>
        {!ready && !busy && !sameWork && !existing && !conflicted && <p>{t('To save, enter what changed and choose a passage and quote from the later work.')}</p>}
        <p>{t('A saved quote is located in the later work’s text. Whether it supports the relation has not been checked.')}</p></footer>
    </SheetContent>
  </Sheet>
}
