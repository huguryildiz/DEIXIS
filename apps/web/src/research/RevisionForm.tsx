import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '../i18n'

// The question bubble turned into the revise form (mockup `.q.edit`, R7): the question, the English key terms, Cancel
// and "Save revision N+1". Saving creates a new question revision; sources and earlier answers are kept.
export function RevisionForm({ question, keyTerms, nextRevision, focus, disabled, onSubmit, onCancel }: {
  question: string; keyTerms: string; nextRevision: number; focus: 'question' | 'terms'
  disabled: boolean; onSubmit: (text: string, keyTerms: string | null) => void; onCancel: () => void
}) {
  const [text, setText] = useState(question)
  const [terms, setTerms] = useState(keyTerms)
  const questionField = useRef<HTMLTextAreaElement>(null)
  const termsField = useRef<HTMLInputElement>(null)
  useEffect(() => { (focus === 'terms' ? termsField : questionField).current?.focus() }, [focus])
  const changed = (text.trim() && text.trim() !== question) || terms.trim() !== keyTerms.trim()
  return <form className="chat-question is-editing" aria-label={t('Revise question')}
    onSubmit={e => { e.preventDefault(); if (changed && text.trim()) onSubmit(text.trim(), terms.trim() || null) }}
    onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel() } }}>
    <label>{t('Question')}<textarea id="revise-question" ref={questionField} rows={4} value={text} dir="auto" onChange={e => setText(e.target.value)} /></label>
    <label>{t('English key terms (optional)')}<input id="revise-key-terms" ref={termsField} value={terms} onChange={e => setTerms(e.target.value)} maxLength={500} dir="auto" aria-describedby="revise-key-terms-hint" /></label>
    <small id="revise-key-terms-hint">{t('Blocks are separated by “;”, synonyms of one block by “,”; a group written “claim:” is the assertion under test and one written “not:” keeps records out.')}</small>
    <div className="chat-question-buttons">
      <Button type="button" variant="ghost" size="sm" className="research-topbar-action" onClick={onCancel}>{t('Cancel')}</Button>
      <Button type="submit" size="sm" disabled={disabled || !text.trim() || !changed}>{t('Save revision {n}', { n: nextRevision })}</Button>
    </div>
  </form>
}
