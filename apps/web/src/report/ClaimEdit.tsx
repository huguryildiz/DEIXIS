import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { ReportClaim } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'

export type ClaimEditBody = { text?: string; note?: string | null; link_ids?: string[]; restore_from?: string }

export function ClaimEdit({ claim, conflicts, save, cancel, busy, error, sourceName }: {
  claim: ReportClaim; conflicts: number; save: (body: ClaimEditBody, expectedVersion: number) => void
  cancel: () => void; busy: boolean; error: string; sourceName: (sourceVersionId: string) => string
}) {
  const [text, setText] = useState(claim.text)
  const [note, setNote] = useState('')
  const [unchecked, setUnchecked] = useState<Set<string>>(() => new Set())
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  // A conflict preserves the draft, but adopts the version from the recovery read actually shown.
  const [expectedVersion, setExpectedVersion] = useState(claim.version)
  const [seenConflicts, setSeenConflicts] = useState(conflicts)
  if (conflicts !== seenConflicts) { setSeenConflicts(conflicts); setExpectedVersion(claim.version) }
  const field = useRef<HTMLTextAreaElement>(null)
  const reasonId = useId()
  useEffect(() => { field.current?.focus() }, [])
  // A removal intent only holds for links that are still effective: one that left and came back reads as kept.
  const effective = new Set(claim.evidence.map(link => link.link_id))
  if ([...unchecked].some(id => !effective.has(id))) setUnchecked(new Set([...unchecked].filter(id => effective.has(id))))
  const kept = claim.evidence.filter(link => !unchecked.has(link.link_id))
  const removed = kept.length !== claim.evidence.length
  const textChanged = text.trim() !== claim.text
  const reason = busy ? t('Saving…') : !text.trim() ? t('Write the sentence or cancel.') : !textChanged && !removed ? t('Change the text or remove a citation to save.') : ''
  const canSave = !reason
  const submit = () => {
    if (!canSave) return
    save({ ...(textChanged ? { text: text.trim() } : {}), note, ...(removed ? { link_ids: kept.map(link => link.link_id) } : {}) }, expectedVersion)
  }
  const toggle = (previous: Set<string>, id: string) => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next }
  return <form className="evidence-report-edit" data-expected-version={expectedVersion} onSubmit={event => { event.preventDefault(); submit() }} onKeyDown={event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancel() }
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); submit() }
  }}>
    <label>{t('Claim text')}<textarea ref={field} data-stored-text value={text} readOnly={busy} onChange={event => setText(event.target.value)} aria-invalid={Boolean(error)} /></label>
    <label>{t('Edit note (optional)')}<input data-stored-text value={note} readOnly={busy} onChange={event => setNote(event.target.value)} /></label>
    {claim.evidence.length > 0 ? <fieldset><legend>{t('Citations to keep')}</legend><ul className="evidence-report-citation-choices">{claim.evidence.map(link => {
      const open = expanded.has(link.link_id), anchor = link.anchor_text ?? '', checked = !unchecked.has(link.link_id)
      return <li key={link.link_id} data-link-id={link.link_id}>
        <label className="evidence-report-citation-choice"><input type="checkbox" checked={checked} aria-disabled={busy} onChange={() => { if (!busy) setUnchecked(previous => toggle(previous, link.link_id)) }} /><span data-stored-text>[{link.ref_number}] {sourceName(link.source_version_id)}</span></label>
        <p className="evidence-report-citation-anchor">{t(link.cell_id ? 'table cell' : 'passage')} · <span data-stored-text>{open || anchor.length <= 160 ? anchor : `${anchor.slice(0, 160)}…`}</span></p>
        {anchor.length > 160 && <Button type="button" size="sm" variant="ghost" aria-expanded={open} onClick={() => setExpanded(previous => toggle(previous, link.link_id))}>{t(open ? 'Show less' : 'Show more')}</Button>}
        {!checked && <p>{t('Will be removed when you save.')}</p>}
      </li>
    })}</ul><p>{t(claim.evidence.length === 1 ? '{k} of {n} citation kept' : '{k} of {n} citations kept', { k: kept.length, n: claim.evidence.length })}</p>{kept.length === 0 && <Notice tone="attention">{t('No citation will remain on this sentence. Its support type stays as the model wrote it, and you can bring the citations back from History.')}</Notice>}</fieldset>
      : <p className="evidence-report-fine">{t(claim.original_evidence_count > 0 ? 'This sentence has no citations to keep. History can bring earlier citations back.' : 'This sentence has no citations to keep.')}</p>}
    {error && <p role="alert" data-stored-text>{error}</p>}
    <div><Button type="submit" disabled={!canSave} aria-describedby={reason ? reasonId : undefined}>{t('Save')}</Button><Button type="button" variant="outline" onClick={cancel}>{t('Cancel')}</Button></div>
    {reason && <p id={reasonId}>{reason}</p>}
  </form>
}
