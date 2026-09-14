import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, FileText, FileUp, History, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api, type Connections, type Effort, type ResearchSummary, type SourceScope } from './api'
import { runStatusLabels, scopeLabels } from './labels'

const effortLabels: Record<Effort, string> = { quick: 'Quick', standard: 'Standard', detailed: 'Detailed' }

export function Home({ researches, onCreated }: { researches: ResearchSummary[]; onCreated: (id: string) => void }) {
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState<SourceScope>('academic')
  const [effort, setEffort] = useState<Effort>('standard')
  const [connections, setConnections] = useState<Connections | null>(null)
  const [model, setModel] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.connections().then(result => {
      setConnections(result)
      const models = result.models.codex?.models ?? []
      const preferred = models.find(m => m.is_default) ?? models[0]
      if (preferred) setModel(current => current || preferred.id)
    }).catch((e: Error) => setError(`Could not read connections: ${e.message}`))
  }, [])

  const codex = connections?.models.codex
  const models = codex?.models ?? []
  const needsFiles = scope === 'attached'

  async function addFiles(list: FileList | null) {
    if (!list) return
    const accepted: File[] = []
    const rejected: string[] = []
    for (const file of Array.from(list)) {
      const header = await file.slice(0, 5).text()
      if (header === '%PDF-') accepted.push(file); else rejected.push(file.name)
    }
    setFiles(old => [...new Map([...old, ...accepted].map(f => [f.name, f])).values()])
    setError(rejected.length ? `${rejected.join(', ')}: only PDF files can be attached.` : '')
  }

  async function submit() {
    if (!question.trim() || busy) return
    if (needsFiles && !files.length) { setError('Attach at least one PDF to use “Attached files”.'); return }
    setBusy(true)
    setError('')
    try {
      const view = await api.create({ question: question.trim(), source_scope: scope, effort, model_connection: 'codex', requested_model: model || null })
      const id = view.research.id
      for (const file of files) await api.upload(id, file)
      if (scope !== 'attached') await api.startRun(id, 'discovery', crypto.randomUUID())
      onCreated(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const caption = needsFiles
    ? 'Only attached PDFs are used; no academic search runs.'
    : `OpenAlex is searched${scope === 'attached_and_academic' ? ' in addition to your PDFs' : ''}; other providers are not connected yet.`

  return <section className="welcome">
    <div className="eyebrow"><span /> A LITTLE CURIOSITY. A CLEARER PICTURE.</div>
    <h1>Where does your<br /><em>question</em>{' '}lead?</h1>
    <p className="intro">Ask a question. DEIXIS finds publications, lets you choose the sources, and links each claim to a passage you can open.</p>
    <form className="composer" onSubmit={e => { e.preventDefault(); void submit() }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void addFiles(e.dataTransfer.files) }}>
      <label className="composer-label" htmlFor="research-question">What would you like to investigate?</label>
      <Textarea id="research-question" aria-label="Research question" placeholder="How is operations research used in molecular communication?" value={question}
        onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit() } }} />
      {files.length > 0 && <div className="attachments" aria-label="PDFs to attach">{files.map(file => <div className="attachment-chip" key={file.name}><button type="button" title={file.name}><FileText size={13} /><span>{file.name}</span><small>PDF</small></button><button type="button" aria-label={`Remove ${file.name}`} onClick={() => setFiles(old => old.filter(f => f.name !== file.name))}><X size={13} /></button></div>)}</div>}
      <div className="composer-controls">
        <div className="composer-options">
          <button type="button" className="composer-add" aria-label="Attach PDF" title="Attach PDF (optional)" onClick={() => fileInput.current?.click()}><FileUp size={17} /></button>
          <Select value={scope} onValueChange={value => { if (value) setScope(value as SourceScope) }}>
            <SelectTrigger aria-label="Source scope"><SelectValue>{(value: string) => scopeLabels[value as SourceScope]}</SelectValue></SelectTrigger>
            <SelectContent className="intake-select-content" align="start" alignItemWithTrigger={false}>{(Object.keys(scopeLabels) as SourceScope[]).map(s => <SelectItem key={s} value={s}>{scopeLabels[s]}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={effort} onValueChange={value => { if (value) setEffort(value as Effort) }}>
            <SelectTrigger aria-label="Research depth"><SelectValue>{(value: string) => effortLabels[value as Effort]}</SelectValue></SelectTrigger>
            <SelectContent className="intake-select-content" align="start" alignItemWithTrigger={false}>{(Object.keys(effortLabels) as Effort[]).map(d => <SelectItem key={d} value={d}>{effortLabels[d]}</SelectItem>)}</SelectContent>
          </Select>
          {models.length > 0
            ? <Select value={model} onValueChange={value => { if (value) setModel(value) }}>
                <SelectTrigger aria-label="Model"><SelectValue>{(value: string) => `Codex · ${models.find(m => m.id === value)?.display_name ?? value}`}</SelectValue></SelectTrigger>
                <SelectContent className="intake-select-content" align="start" alignItemWithTrigger={false}>{models.map(m => <SelectItem key={m.id} value={m.id}>{m.display_name}{m.is_default ? ' · Codex default' : ''}</SelectItem>)}</SelectContent>
              </Select>
            : <span className="composer-model" title={codex?.reason ?? ''}>Model: {connections ? 'Codex not ready' : 'checking…'}</span>}
        </div>
        <Button className="send-button" type="submit" size="icon" disabled={!question.trim() || busy || (needsFiles && !files.length)} aria-label="Start research"><ArrowUpRight size={20} /></Button>
      </div>
    </form>
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void addFiles(e.target.files); e.target.value = '' }} />
    <div className="composer-caption"><span>{busy ? 'Saving research…' : caption}</span><span>⌘ / Ctrl + Enter</span></div>
    {codex && !codex.ready && <div className="legacy-boundary">Codex is not ready: {codex.reason}. Your research is still saved; model steps pause until the connection is ready. No other model is used instead.</div>}
    {error && <div className="legacy-boundary" role="alert">{error}</div>}
    <div className="resume-section">
      <div className="resume-heading"><h2>Pick up where you left off</h2><span>SAVED ON THIS COMPUTER</span></div>
      <div className="resume-list">
        {researches.slice(0, 5).map(r => <button key={r.id} onClick={() => onCreated(r.id)}><History size={18} /><span><strong>{r.question}</strong><small>{scopeLabels[r.source_scope]} · {r.last_run_status ? runStatusLabels[r.last_run_status] : 'No run yet'} · {r.answer_count} answer{r.answer_count === 1 ? '' : 's'}</small></span><ArrowUpRight size={16} /></button>)}
        {!researches.length && <p className="empty-inline">No saved research yet.</p>}
      </div>
    </div>
  </section>
}
