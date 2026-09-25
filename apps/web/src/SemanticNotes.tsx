import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type ResearchView } from './api'
import { Notice } from './Notice'
import { t } from './i18n'

// Under the answer and table buttons whenever Gemini or OpenAI ranks passages (slice 21, decision 10). What will be
// sent cannot be known when the button is pressed, so the line is conditional and promises no count; what was sent is
// recorded by the step afterwards.
export function UploadedTextNote({ semantic }: { semantic?: ResearchView['semantic'] }) {
  if (semantic?.provider === 'gemini') return <p className="semantic-upload-note">{t('If the included sources have PDFs you uploaded, their text is sent to Google to rank passages. On Google’s free tier, Google may use it to improve its products.')}</p>
  if (semantic?.provider === 'openai') return <p className="semantic-upload-note">{t('If the included sources have PDFs you uploaded, their text is sent to OpenAI to rank passages.')}</p>
  return null
}

// At the top of the Sources tab when the built-in model is chosen (slice 21, decision 11): the English sentence it
// reads, or the form to write one when the question is not in English. Written once per question revision.
export function EnglishQuestion({ researchId, view, busy, onSaved }: {
  researchId: string; view: ResearchView; busy: boolean; onSaved: (next: ResearchView) => void
}) {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const semantic = view.semantic
  if (!semantic || semantic.provider !== 'builtin') return null
  // The same rule as the query: the sentence is read only when the question is not read as English.
  if (semantic.needs_english_question && semantic.english_question) return <p className="english-question-line">{t('Built-in model uses: {text}', { text: semantic.english_question.text })}</p>
  if (semantic.arm !== 'english_question_missing') return null
  const save = (body: { text: string; expected_version: number } | { use_question: true; expected_version: number }) => {
    setSaving(true)
    setError('')
    api.saveEnglishQuestion(researchId, body).then(onSaved).catch((e: Error) => setError(e.message)).finally(() => setSaving(false))
  }
  return <div className="english-question">
    <Notice tone="attention">{t('The built-in semantic model reads English only. This question is not in English, so the built-in model is off for this research. Add one English sentence that says what you are looking for.')}</Notice>
    <form onSubmit={e => { e.preventDefault(); if (text.trim()) save({ text: text.trim(), expected_version: view.research.version }) }}>
      <label className="sr-only" htmlFor="english-question-text">{t('English sentence for the built-in model')}</label>
      <input id="english-question-text" value={text} maxLength={500} onChange={e => setText(e.target.value)} placeholder={t('One English sentence')} disabled={saving || busy} />
      <Button type="submit" size="sm" disabled={saving || busy || !text.trim()}>{t(saving ? 'Saving…' : 'Save')}</Button>
      <Button type="button" size="sm" variant="ghost" disabled={saving || busy} onClick={() => save({ use_question: true, expected_version: view.research.version })}>{t('The question is already in English')}</Button>
    </form>
    {error && <p className="local-tool-error" role="alert">{error}</p>}
  </div>
}
