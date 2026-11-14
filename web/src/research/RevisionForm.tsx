import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '../lib/i18n'

// The question bubble turned into the revise form (mockup `.q.edit`, R7): the question, the English key terms, what
// saving does, Cancel and "Save revision N". Saving creates a new question revision; sources and earlier answers are
// kept. N is the next free number: a withdrawn revision's number is not used again.
// `conflict` names a newer revision saved elsewhere while the form was open: the draft stays, and Save waits until the
// person bases the draft on that revision.
// `englishQuestion`: the current revision's English sentence when the question is not English, '' when it has
// none yet, null when the question is English and the field is not shown. The sentence is sent only when changed: an
// edited one is the person's for the new revision, a cleared one lets the model translate it.
export function RevisionForm({ question, keyTerms, englishQuestion = null, nextRevision, focus, focusRequest, conflict, disabled, onSubmit, onCancel, onRebase }: {
  question: string; keyTerms: string; englishQuestion?: string | null; nextRevision: number; focus: 'question' | 'terms'; focusRequest: number; conflict: number | null
  onRebase: () => void; disabled: boolean; onSubmit: (text: string, keyTerms: string | null, englishQuestion?: string) => void; onCancel: () => void
}) {
  const [text, setText] = useState(question)
  const [terms, setTerms] = useState(keyTerms)
  const [english, setEnglish] = useState(englishQuestion ?? '')
  const englishChanged = englishQuestion !== null && english.trim() !== englishQuestion.trim()
  const questionField = useRef<HTMLTextAreaElement>(null)
  const termsField = useRef<HTMLInputElement>(null)
  useEffect(() => { (focus === 'terms' ? termsField : questionField).current?.focus() }, [focus, focusRequest])
  const changed = (text.trim() && text.trim() !== question) || terms.trim() !== keyTerms.trim() || englishChanged
  // A cleared field that had stored terms is sent as '': null would carry the old terms over to the new revision.
  return <form className="chat-question is-editing" aria-label={t('Revise question')}
    onSubmit={e => { e.preventDefault(); if (!conflict && changed && text.trim()) onSubmit(text.trim(), keyTerms.trim() ? terms.trim() : terms.trim() || null, englishChanged ? english.trim() : undefined) }}
    onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel() } }}>
    {conflict !== null && <div className="revise-conflict" role="alert">
      <p>{t('Revision {n} of this question was saved in another window while you edited. Your draft is kept below.', { n: conflict })}</p>
      <p className="revise-conflict-question" dir="auto">{question}</p>
      <Button type="button" variant="ghost" size="sm" className="research-topbar-action" onClick={() => { onRebase(); questionField.current?.focus() }}>{t('Base my draft on revision {n}', { n: conflict })}</Button>
    </div>}
    <label>{t('Question')}<textarea id="revise-question" ref={questionField} rows={4} value={text} dir="auto" onChange={e => setText(e.target.value)} /></label>
    <label>{t('English key terms (optional)')}<input id="revise-key-terms" ref={termsField} value={terms} onChange={e => setTerms(e.target.value)} maxLength={500} dir="auto" aria-describedby="revise-key-terms-hint" /></label>
    {englishQuestion !== null && <label>{t('English sentence for planning and ranking (optional)')}<input id="revise-english-question" value={english} onChange={e => setEnglish(e.target.value)} maxLength={500} dir="auto" aria-describedby="revise-english-question-hint" /></label>}
    {englishQuestion !== null && <small id="revise-english-question-hint">{terms.trim()
      ? t('Question words for ranking and screening come from the key terms above.')
      : t('Question words for ranking and screening come from this sentence. Leave it empty to have the model translate the question again.')}</small>}
    <p className="revise-effect">{t('Saving makes this revision {n} of the research question and names the research after it. No search starts. A work read under the current question is not used by an answer until a search under the new question reads it again. While nothing has been searched, answered or read under it, you can undo it.', { n: nextRevision })}</p>
    <small id="revise-key-terms-hint">{t('Blocks are separated by “;”, synonyms of one block by “,”; a group written “claim:” is the assertion under test and one written “not:” keeps records out.')}</small>
    <div className="chat-question-buttons">
      <Button type="button" variant="ghost" size="sm" className="research-topbar-action" onClick={onCancel}>{t('Cancel')}</Button>
      <Button type="submit" size="sm" disabled={disabled || conflict !== null || !text.trim() || !changed}>{t('Save revision {n}', { n: nextRevision })}</Button>
    </div>
  </form>
}
