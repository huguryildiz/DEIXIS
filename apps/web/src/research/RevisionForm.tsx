import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '../i18n'

// `keyTerms` null: this research does not run the sw workflow, and its search words are not read from key terms.
export function RevisionForm({ question, keyTerms, keyTermsRef, disabled, onSubmit }: {
  question: string; keyTerms: string | null; keyTermsRef: React.RefObject<HTMLInputElement | null>
  disabled: boolean; onSubmit: (text: string, keyTerms: string | null) => void
}) {
  const [text, setText] = useState(question)
  const [terms, setTerms] = useState(keyTerms ?? '')
  const changed = (text.trim() && text.trim() !== question) || terms.trim() !== (keyTerms ?? '').trim()
  return <form className="legacy-followup" onSubmit={e => { e.preventDefault(); if (changed && text.trim()) onSubmit(text.trim(), terms.trim() || null) }}>
    <label htmlFor="revise-question">{t('Revise the question')}</label>
    <textarea id="revise-question" value={text} onChange={e => setText(e.target.value)} />
    {keyTerms !== null && <div className="revise-key-terms">
      <label htmlFor="revise-key-terms">{t('English key terms (optional)')}</label>
      <input id="revise-key-terms" ref={keyTermsRef} value={terms} onChange={e => setTerms(e.target.value)} maxLength={500} dir="auto" />
      <small>{t('Blocks are separated by “;”, synonyms of one block by “,”; a group written “claim:” is the assertion under test and one written “not:” keeps records out.')}</small>
    </div>}
    <div><span>{t('Creates a new question revision. Sources and earlier answers are kept.')}</span><Button type="submit" disabled={disabled || !text.trim() || !changed}>{t('Save revision')}</Button></div>
  </form>
}
