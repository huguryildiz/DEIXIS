import { useEffect, useRef, useState, type RefObject } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, ApiError, type CandidateCard, type CandidateEdit, type CandidateElementKind } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { errorText, kindLabels, label } from './labels'

export function CandidateEditor({ card, researchId, dark, returnFocus, beginMutation, onSaved, onReload, onClose }: {
  card: CandidateCard; researchId: string; dark: boolean; returnFocus: RefObject<HTMLElement | null>
  beginMutation: () => number; onSaved: (card: CandidateCard, request: number) => void; onReload: () => Promise<CandidateCard>; onClose: () => void
}) {
  const version = card.versions.find(v => v.id === card.current_version_id)
  const firstField = useRef<HTMLTextAreaElement>(null)
  const sessionOpen = useRef(true)
  useEffect(() => { sessionOpen.current = true; return () => { sessionOpen.current = false } }, [])
  const close = () => { sessionOpen.current = false; onClose() }
  const [fields, setFields] = useState<CandidateEdit>(() => ({ claim_statement: version?.claim_statement ?? card.origin_text, conditions: version?.conditions ?? [],
    elements: version?.elements.map(e => ({ text: e.text, kind: e.kind })) ?? [], nearest_simple_explanation: version?.nearest_simple_explanation ?? null,
    critical_assumption: version?.critical_assumption ?? '', validation_plan: version?.validation_plan ?? '', expected_version: card.current_version }))
  const [none, setNone] = useState(fields.nearest_simple_explanation === null)
  const [explanation, setExplanation] = useState(fields.nearest_simple_explanation ?? '')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const [conflicted, setConflicted] = useState(false)
  const patch = (change: Partial<CandidateEdit>) => setFields(value => ({ ...value, ...change }))
  const ready = fields.claim_statement.length > 0 && fields.elements.length >= 2 && fields.elements.length <= 6
    && fields.elements.every(e => e.text.trim()) && fields.conditions.every(c => c.trim())
    && fields.critical_assumption.trim().length > 0 && fields.validation_plan.trim().length > 0 && (none || explanation.trim().length > 0)
  async function save() {
    if (!ready || busy || conflicted) return
    const request = beginMutation()
    setBusy(true); setProblem('')
    try {
      const fresh = await api.editCandidate(researchId, card.id, { ...fields, nearest_simple_explanation: none ? null : explanation })
      // The stored version still applies after cancellation; only this editor session may close.
      onSaved(fresh, request)
      if (sessionOpen.current) close()
    }
    catch (e) { if (sessionOpen.current) { setConflicted(e instanceof ApiError && e.status === 409); setProblem(errorText(e)) } }
    finally { if (sessionOpen.current) setBusy(false) }
  }
  async function reload() {
    setBusy(true)
    try { const fresh = await onReload(); if (sessionOpen.current) { patch({ expected_version: fresh.current_version }); setConflicted(false); setProblem('') } }
    catch (e) { if (sessionOpen.current) setProblem(errorText(e)) }
    finally { if (sessionOpen.current) setBusy(false) }
  }
  const textField = (name: 'claim_statement' | 'critical_assumption' | 'validation_plan', title: string) => <label className="evidence-field"><span>{t(title)}</span><small>{t('{n}/{max} characters', { n: fields[name].length, max: 4000 })}</small><textarea ref={name === 'claim_statement' ? firstField : undefined} aria-label={t(title)} required rows={3} maxLength={4000} value={fields[name]} onChange={e => patch({ [name]: e.target.value })} /></label>
  return <Sheet open onOpenChange={open => { if (!open) close() }}><SheetContent className={`detail-sheet evidence-sheet candidate-editor ${dark ? 'dark' : ''}`} initialFocus={firstField} finalFocus={returnFocus}>
    <SheetHeader><SheetTitle>{t('Write the candidate card')}</SheetTitle><SheetDescription>{t('Saving creates a new version. Earlier searches stay with their versions.')}</SheetDescription></SheetHeader>
    <form id="candidate-edit-form" className="sheet-body evidence-form candidate-form" onSubmit={e => { e.preventDefault(); void save() }}>
      {textField('claim_statement', 'Claim statement')}
      <h3>{t('Conditions')}</h3><ol>{fields.conditions.map((condition, i) => <li key={i}><label className="evidence-field"><span>{t('Condition {n}', { n: i + 1 })}</span><small>{t('{n}/{max} characters', { n: condition.length, max: 2000 })}</small><textarea required maxLength={2000} value={condition} onChange={e => patch({ conditions: fields.conditions.map((c, j) => i === j ? e.target.value : c) })} /></label><Button type="button" variant="ghost" onClick={() => patch({ conditions: fields.conditions.filter((_, j) => i !== j) })}>{t('Remove condition {n}', { n: i + 1 })}</Button></li>)}</ol>
      {!fields.conditions.length && <p>{t('None.')}</p>}<Button type="button" variant="outline" disabled={fields.conditions.length >= 24} aria-describedby="candidate-condition-limit" onClick={() => patch({ conditions: [...fields.conditions, ''] })}>{t('Add condition')}</Button><p id="candidate-condition-limit">{t('At most 24 conditions.')}</p>
      <h3>{t('Elements')}</h3><p id="candidate-element-limit">{t('A card needs 2 to 6 elements.')}</p><ol>{fields.elements.map((element, i) => <li key={i}>
        <label className="evidence-field"><span>{t('Element {n} kind', { n: i + 1 })}</span><select value={element.kind} onChange={e => patch({ elements: fields.elements.map((item, j) => i === j ? { ...item, kind: e.target.value as CandidateElementKind } : item) })}>{['mechanism', 'condition', 'outcome', 'parameter'].map(kind => <option key={kind} value={kind}>{label(kindLabels, kind)}</option>)}</select></label>
        <label className="evidence-field"><span>{t('Element {n} text', { n: i + 1 })}</span><small>{t('{n}/{max} characters', { n: element.text.length, max: 2000 })}</small><textarea aria-label={t('Element {n} text', { n: i + 1 })} required maxLength={2000} value={element.text} onChange={e => patch({ elements: fields.elements.map((item, j) => i === j ? { ...item, text: e.target.value } : item) })} /></label>
        <Button type="button" variant="ghost" disabled={fields.elements.length <= 2} aria-describedby="candidate-element-limit" onClick={() => patch({ elements: fields.elements.filter((_, j) => i !== j) })}>{t('Remove element {n}', { n: i + 1 })}</Button></li>)}</ol>
      {!fields.elements.length && <p>{t('None.')}</p>}<Button type="button" variant="outline" disabled={fields.elements.length >= 6} aria-describedby="candidate-element-limit" onClick={() => patch({ elements: [...fields.elements, { kind: 'mechanism', text: '' }] })}>{t('Add element')}</Button>
      {fields.elements.length <= 2 && <p>{t('At least two elements are required; removal is unavailable at two.')}</p>}{fields.elements.length >= 6 && <p>{t('Six elements reached; another cannot be added.')}</p>}
      <label className="evidence-field"><span>{t('Nearest simple explanation')}</span><small>{t('{n}/{max} characters', { n: explanation.length, max: 4000 })}</small><textarea aria-label={t('Nearest simple explanation')} disabled={none} aria-describedby={none ? 'candidate-explanation-none' : undefined} maxLength={4000} value={explanation} onChange={e => setExplanation(e.target.value)} /></label>
      <label id="candidate-explanation-none" className="evidence-check"><input type="checkbox" checked={none} onChange={e => setNone(e.target.checked)} />{t('None')}</label>
      {textField('critical_assumption', 'Critical assumption')}{textField('validation_plan', 'Validation plan')}
      <p>{t('Critical assumption and validation plan are required; blank text is refused when saving.')}</p>
      {problem && <Notice tone="error">{conflicted && <p>{t('This card changed since you opened it')}</p>}{problem}{conflicted && <Button type="button" variant="ghost" disabled={busy} onClick={() => void reload()}>{t('Reload')}</Button>}</Notice>}
    </form><footer className="cell-foot"><div className="candidate-actions"><Button type="submit" form="candidate-edit-form" disabled={!ready || busy || conflicted} aria-describedby="candidate-save-reason">{t('Save')}</Button><Button variant="outline" onClick={close}>{t('Cancel')}</Button></div>{(!ready || busy || conflicted) && <p id="candidate-save-reason">{t(conflicted ? 'Reload before saving; your typed text is kept.' : busy ? 'Saving…' : 'Enter the required text and 2 to 6 elements to save.')}</p>}</footer>
  </SheetContent></Sheet>
}
