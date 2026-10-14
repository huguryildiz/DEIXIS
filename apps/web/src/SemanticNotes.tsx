import { useCallback, useEffect, useRef, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, ApiError, type BuiltinEmbedding, type ResearchView, type SemanticSearch } from './api'
import { Notice } from './Notice'
import { t } from './i18n'

// On Home when semantic search is off only because nothing is saved in Settings, no Gemini key is set and the built-in
// model is not downloaded (D7). Downloading is the person's act; once the model is ready the backend uses it while
// nothing is saved, so this note saves no choice and simply goes away. Never shown after the person chose Off.
const aboutMb = (bytes: number) => Math.round(bytes / 1e6)

export function SemanticSetupNote() {
  const [semantic, setSemantic] = useState<SemanticSearch | null>(null)
  const [builtin, setBuiltin] = useState<BuiltinEmbedding | null>(null)
  const [starting, setStarting] = useState(false)
  // A failed check and a failed start are kept apart, so a later successful check never hides why a start failed.
  const [loadError, setLoadError] = useState('')
  const [startError, setStartError] = useState('')
  const alive = useRef(false)
  const seq = useRef(0)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  // Only the newest load may set state, so a slow earlier reply never brings back an older state.
  const load = useCallback(() => {
    const mine = ++seq.current
    return Promise.all([api.semanticSearch(), api.builtinEmbedding()]).then(([s, b]) => {
      if (!alive.current || mine !== seq.current) return
      setSemantic(s); setBuiltin(b); setLoadError('')
    }).catch((e: Error) => { if (alive.current && mine === seq.current) setLoadError(e.message) })
  }, [])
  // A choice saved or a download finished in another tab shows when the person comes back to this one.
  useEffect(() => {
    void load()
    const again = () => { if (document.visibilityState === 'visible') void load() }
    window.addEventListener('focus', again)
    document.addEventListener('visibilitychange', again)
    return () => { window.removeEventListener('focus', again); document.removeEventListener('visibilitychange', again) }
  }, [load])
  const status = builtin?.status
  useEffect(() => {
    if (status !== 'installing' && status !== 'installing_elsewhere') return
    let stopped = false
    let timer = 0
    const tick = () => { timer = window.setTimeout(() => { void load().finally(() => { if (!stopped) tick() }) }, 1500) }
    tick()
    return () => { stopped = true; window.clearTimeout(timer) }
  }, [status, load])
  const retry = <Button type="button" variant="link" size="sm" onClick={() => { void load() }}>{t('Check again')}</Button>
  if ((!semantic || !builtin) && loadError) return <Notice tone="error">{t('Could not check semantic search: {message}', { message: loadError })} {retry}</Notice>
  if (!semantic || !builtin || semantic.provider !== 'off' || semantic.explicit || builtin.status === 'unsupported_platform') return null
  if (builtin.status === 'ready' || (builtin.status === 'update_available' && builtin.available) || builtin.status === 'removing' || builtin.status === 'remove_failed') return null
  const install = () => {
    setStarting(true)
    setStartError('')
    api.installBuiltinEmbedding()
      .then(({ job }) => { if (alive.current) setBuiltin(current => current && current.status !== 'unsupported_platform' ? { ...current, status: 'installing', job } : current) })
      // Started in another tab, or already done there: the next load shows that download or the ready model. Any other
      // refusal (another DEIXIS process using the model, uv missing) is said.
      .catch((e: Error) => {
        const settled = e instanceof ApiError && (e.reason === 'install_running' || e.reason === 'already_installed')
        if (alive.current && !settled) setStartError(e.message)
      })
      .finally(() => { if (alive.current) { setStarting(false); void load() } })
  }
  const { sizes, job } = builtin
  const running = builtin.status === 'installing' || builtin.status === 'installing_elsewhere'
  const mismatch = builtin.status === 'files_do_not_match'
  const sizeVars = { total: aboutMb(sizes.runtime_bytes + sizes.model_bytes), python: aboutMb(sizes.python_bytes) }
  return <Notice tone="info">
    <p className="semantic-setup-text">{t('Semantic search is off, so sources are ranked by their keywords only. The built-in model ranks them by meaning; it runs on this computer and needs no key.')}</p>
    {!running && <p className="semantic-setup-text">{t('It needs about {total} MB of disk, plus about {python} MB if Python 3.12 has to be downloaded, plus room for a download cache.', sizeVars)}</p>}
    {mismatch && <p className="local-tool-error">{t('The model files do not match the checked copy, so the model is not used. Download them again.')}</p>}
    {builtin.status === 'failed' && <p className="local-tool-error">{t('The last download failed. Settings → Connections shows the details.')}</p>}
    {running && <p className="semantic-setup-progress" role="status"><LoaderCircle size={14} className="chat-spin" aria-hidden />
      {job && builtin.status === 'installing' ? t('Downloading the built-in model: step {step} of {steps}', { step: job.step, steps: job.steps }) : t('Downloading the built-in model…')}</p>}
    {startError && <p className="local-tool-error" role="alert">{startError}</p>}
    {loadError && <p className="local-tool-error" role="alert">{loadError} {retry}</p>}
    {!running && (builtin.uv.available
      ? <Button type="button" size="sm" variant="outline" disabled={starting} onClick={install}>{starting ? <><LoaderCircle size={14} className="chat-spin" aria-hidden />{t('Starting the download…')}</> : t(mismatch || builtin.status === 'failed' ? 'Download the built-in model again' : 'Download the built-in model')}</Button>
      : <p>{t('The download needs uv. Settings → Connections → Semantic search shows how to install it.')}</p>)}
  </Notice>
}

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
    <Notice tone="attention">{t('The built-in model reads English only, so it is off for this research. Add one English sentence that says what you are looking for.')}</Notice>
    <form onSubmit={e => { e.preventDefault(); if (text.trim()) save({ text: text.trim(), expected_version: view.research.version }) }}>
      <label className="sr-only" htmlFor="english-question-text">{t('English sentence for the built-in model')}</label>
      <input id="english-question-text" value={text} maxLength={500} onChange={e => setText(e.target.value)} placeholder={t('One English sentence')} disabled={saving || busy} />
      <Button type="submit" size="sm" disabled={saving || busy || !text.trim()}>{t(saving ? 'Saving…' : 'Save')}</Button>
      <Button type="button" size="sm" variant="ghost" disabled={saving || busy} onClick={() => save({ use_question: true, expected_version: view.research.version })}>{t('The question is already in English')}</Button>
    </form>
    {error && <p className="local-tool-error" role="alert">{error}</p>}
  </div>
}
