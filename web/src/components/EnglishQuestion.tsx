import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type ResearchView } from '../lib/api'
import { Notice } from './Notice'
import { t } from '../lib/i18n'

// The English sentence used by search and reranking for a non-English question.
export function EnglishQuestion({ researchId, view, busy, onSaved }: {
  researchId: string; view: ResearchView; busy: boolean; onSaved: (next: ResearchView) => void
}) {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  if (!view.scope.needs_english_question) return null
  if (view.scope.english_question) return <p className="english-question-line">{t('English version of the question: {text}', { text: view.scope.english_question.text })}</p>
  const save = (body: { text: string; expected_version: number } | { use_question: true; expected_version: number }) => {
    setSaving(true)
    setError('')
    api.saveEnglishQuestion(researchId, body).then(onSaved).catch((e: Error) => setError(e.message)).finally(() => setSaving(false))
  }
  return <div className="english-question">
    <Notice tone="attention">{t('Add an English sentence for searching and reranking this question.')}</Notice>
    <form onSubmit={e => { e.preventDefault(); if (text.trim()) save({ text: text.trim(), expected_version: view.research.version }) }}>
      <label className="sr-only" htmlFor="english-question-text">{t('English sentence')}</label>
      <input id="english-question-text" value={text} maxLength={500} onChange={e => setText(e.target.value)} placeholder={t('One English sentence')} disabled={saving || busy} />
      <Button type="submit" size="sm" disabled={saving || busy || !text.trim()}>{saving ? <span className="shimmer-text">{t('Saving…')}</span> : t('Save')}</Button>
      <Button type="button" size="sm" variant="ghost" disabled={saving || busy} onClick={() => save({ use_question: true, expected_version: view.research.version })}>{t('The question is already in English')}</Button>
    </form>
    {error && <p className="local-tool-error" role="alert">{error}</p>}
  </div>
}
