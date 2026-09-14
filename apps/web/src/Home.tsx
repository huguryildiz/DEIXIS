import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowUpRight, BookMarked, Brain, ChevronDown, FileText, FileUp, Gauge, Globe, History, Layers, Library, Link2, Paperclip, PenLine, ScanSearch, ShieldCheck, Sparkles, Telescope, X, Zap, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from './Toast'
import { api, type Connections, type Effort, type ModelOption, type ModelRole, type ResearchSummary, type RoleModelSetting, type SourceScope, type ZoteroSource } from './api'
import { reasoningLabel, runStatusLabels, scopeLabels } from './labels'
import { t, uiLanguage, uiLocale } from './i18n'
import { ZoteroPanel } from './ZoteroPanel'
import { ConnectionIcon } from './connectionIcons'

export const effortLabels: Record<Effort, string> = { quick: 'Quick', standard: 'Standard', detailed: 'Detailed' }

// Limits mirror TEST_EFFORT_BUDGETS in backend/deixis/domain/rules.py.
export const scopeOptions: Record<SourceScope, { icon: LucideIcon; detail: string }> = {
  academic: { icon: Globe, detail: 'Searches the connected scholarly providers' },
  attached: { icon: Paperclip, detail: 'Only the PDFs you add; no search runs' },
  attached_and_academic: { icon: Layers, detail: 'Your PDFs plus a scholarly provider search' },
}
export const effortOptions: Record<Effort, { icon: LucideIcon; detail: string }> = {
  quick: { icon: Zap, detail: 'Up to 3 searches of 10 results, 20 candidates, 16 passages' },
  standard: { icon: Gauge, detail: 'Up to 8 searches of 25 results, 150 candidates, 48 passages' },
  detailed: { icon: Telescope, detail: 'Up to 12 searches of 25 results, 200 candidates, 80 passages' },
}

export function Option({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail?: ReactNode }) {
  return <span className="intake-option"><Icon size={16} /><span><strong>{title}</strong>{detail && <small>{detail}</small>}</span></span>
}

// Each model lists its own efforts; a picker starts from the one Codex marks as the model's default.
export const defaultEffort = (models: ModelOption[], id: string) => {
  const m = models.find(x => x.id === id)
  return m?.default_reasoning_effort ?? m?.reasoning_efforts?.[0]?.id ?? null
}
const listedEffort = (models: ModelOption[], id: string, effort: string | null) =>
  models.find(m => m.id === id)?.reasoning_efforts?.some(e => e.id === effort) ? effort : null

const DEFAULT_REVIEWER = '__default'
const NO_REVIEW = '__off'

// Step roles and what each does; the composer and Settings describe them the same way. Text is English; callers use t().
export const modelRoles: Record<ModelRole, { label: string; icon: LucideIcon; hint: string }> = {
  answer: { label: 'Answer', icon: PenLine, hint: 'Writes the answer from the passages of the sources you include, linking each claim to its passage.' },
  literature: { label: 'Literature', icon: ScanSearch, hint: 'Plans the searches in the scholarly providers and proposes which results to include. You make the final selection.' },
  reviewer: { label: 'Reviewer', icon: ShieldCheck, hint: 'When an answer is ready, checks each claim against the passages it cites. It never changes the answer and is not independent verification.' },
}

// One model role (answer, literature, reviewer): a model and, when the model lists them, its reasoning effort.
// `choices` are non-model entries such as "Default" or "Off"; they have no effort.
export function ModelPicker({ role, icon: Icon, hint, models, value, onChange, effort, onEffort, choices = [] }: {
  role: string; icon: LucideIcon; hint: string; models: ModelOption[]; value: string; onChange: (value: string) => void
  effort: string | null; onEffort: (effort: string) => void; choices?: { value: string; title: string; detail: string }[]
}) {
  const chosen = models.find(m => m.id === value)
  const efforts = chosen?.reasoning_efforts ?? []
  const name = (v: string) => choices.find(c => c.value === v)?.title ?? models.find(m => m.id === v)?.display_name ?? v
  return <div className="model-role">
    <Select value={value} onValueChange={v => { if (v) onChange(v) }}>
      <SelectTrigger aria-label={t('{role} model', { role })} title={hint}><SelectValue>{(v: string) => <><Icon size={15} /><span className="model-role-name">{role}</span>{name(v)}</>}</SelectValue></SelectTrigger>
      <SelectContent className="intake-select-content has-details" align="start" alignItemWithTrigger={false}>
        <div className="intake-select-heading" aria-hidden="true">{t('{role} MODEL · CODEX', { role: role.toLocaleUpperCase(uiLocale()) })}</div>
        <p className="intake-select-description" aria-hidden="true">{hint}</p>
        {choices.map(c => <SelectItem key={c.value} value={c.value}><Option icon={Icon} title={c.title} detail={c.detail} /></SelectItem>)}
        {models.map(m => <SelectItem key={m.id} value={m.id}><Option icon={Sparkles} title={m.display_name} detail={[m.description, m.is_default ? t('Codex default') : ''].filter(Boolean).join(' · ') || undefined} /></SelectItem>)}
      </SelectContent>
    </Select>
    {efforts.length > 0 && effort &&
      <Select value={effort} onValueChange={v => { if (v) onEffort(v) }}>
        <SelectTrigger aria-label={t('{role} reasoning effort', { role })} title={t('How long the {role} model thinks', { role: role.toLocaleLowerCase(uiLocale()) })}><SelectValue>{(v: string) => <><Brain size={15} />{reasoningLabel(v)}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content has-details" align="start" alignItemWithTrigger={false}>
          <div className="intake-select-heading" aria-hidden="true">{t('{role} REASONING EFFORT', { role: role.toLocaleUpperCase(uiLocale()) })}</div>
          <p className="intake-select-description" aria-hidden="true">{t('How long the {role} model reasons before it replies. Higher settings take longer.', { role: role.toLocaleLowerCase(uiLocale()) })}</p>
          {efforts.map(e => <SelectItem key={e.id} value={e.id}><Option icon={Brain} title={reasoningLabel(e.id)} detail={[e.description, e.id === chosen?.default_reasoning_effort ? t('Model default') : ''].filter(Boolean).join(' · ') || undefined} /></SelectItem>)}
        </SelectContent>
      </Select>}
  </div>
}

export function Home({ researches, onCreated }: { researches: ResearchSummary[]; onCreated: (id: string) => void }) {
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState<SourceScope>('academic')
  const [effort, setEffort] = useState<Effort>('standard')
  const [connections, setConnections] = useState<Connections | null>(null)
  const [model, setModel] = useState('')
  const [reasoning, setReasoning] = useState<string | null>(null)
  const [literature, setLiterature] = useState('')
  const [literatureReasoning, setLiteratureReasoning] = useState<string | null>(null)
  const [reviewer, setReviewer] = useState(DEFAULT_REVIEWER)
  const [reviewerReasoning, setReviewerReasoning] = useState<string | null>(null)
  const [defaults, setDefaults] = useState<Record<ModelRole, RoleModelSetting> | null>(null)
  const [modelsOpen, setModelsOpen] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  // A Zotero collection chosen before the research exists; it is imported right after the research is created.
  const [zotero, setZotero] = useState<{ source: ZoteroSource; key: string; name: string } | null>(null)
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const toast = useToast()

  useEffect(() => {
    Promise.all([api.connections(), api.settings().catch(() => null)]).then(([result, saved]) => {
      setConnections(result)
      setDefaults(saved)
      const models = result.models.codex?.models ?? []
      const preferred = models.find(m => m.is_default) ?? models[0]
      // A default from Settings applies while Codex still lists it; otherwise the composer starts from Codex's default model.
      const start = (setting: RoleModelSetting | undefined) => {
        const id = setting?.model && models.some(m => m.id === setting.model) ? setting.model : preferred?.id
        if (!id) return null
        return { id, effort: (id === setting?.model ? listedEffort(models, id, setting.reasoning_effort) : null) ?? defaultEffort(models, id) }
      }
      const answer = start(saved?.answer)
      const literature = start(saved?.literature)
      if (answer) { setModel(answer.id); setReasoning(answer.effort) }
      if (literature) { setLiterature(literature.id); setLiteratureReasoning(literature.effort) }
    }).catch((e: Error) => setError(t('Could not read connections: {message}', { message: e.message })))
  }, [])

  const codex = connections?.models.codex
  const models = codex?.models ?? []
  const chosen = models.find(m => m.id === model)
  const efforts = chosen?.reasoning_efforts ?? []
  const needsFiles = scope === 'attached'

  function chooseModel(id: string, list = models) {
    const next = list.find(m => m.id === id)
    setModel(id)
    // Each model lists its own efforts; start from the one Codex marks as its default.
    setReasoning(next?.default_reasoning_effort ?? next?.reasoning_efforts?.[0]?.id ?? null)
  }

  async function addFiles(list: FileList | null) {
    if (!list) return
    const accepted: File[] = []
    const rejected: string[] = []
    for (const file of Array.from(list)) {
      const header = await file.slice(0, 5).text()
      if (header === '%PDF-') accepted.push(file); else rejected.push(file.name)
    }
    setFiles(old => [...new Map([...old, ...accepted].map(f => [f.name, f])).values()])
    if (accepted.length && scope === 'academic') setScope('attached_and_academic')  // attachments must be part of the scope
    setError(rejected.length ? t('{files}: only PDF files can be attached.', { files: rejected.join(', ') }) : '')
  }

  async function submit() {
    if (!question.trim() || busy) return
    if (needsFiles && !files.length && !zotero) { setError(t('Attach at least one PDF to use “Attached files”.')); return }
    if (!model || !literature) { setError(t('Choose the answer and literature models first. DEIXIS does not pick them for you.')); return }
    setBusy(true)
    setError('')
    let id: string | null = null
    let step = ''
    const customReviewer = reviewer !== DEFAULT_REVIEWER && reviewer !== NO_REVIEW
    try {
      const view = await api.create({ question: question.trim(), source_scope: scope, effort, model_connection: 'codex', requested_model: model,
        reasoning_effort: efforts.some(e => e.id === reasoning) ? reasoning : null,
        literature_model: literature, literature_reasoning_effort: listedEffort(models, literature, literatureReasoning),
        review_mode: customReviewer ? 'custom' : reviewer === NO_REVIEW ? 'off' : 'default', review_model: customReviewer ? reviewer : null,
        review_reasoning_effort: customReviewer ? listedEffort(models, reviewer, reviewerReasoning) : null })
      id = view.research.id
      step = 'Research saved, but DEIXIS could not attach the PDFs: {message}. You can retry from the research page.'
      for (const file of files) await api.upload(id, file)
      step = 'Research saved, but DEIXIS could not import the Zotero collection: {message}. You can retry from the research page.'
      if (zotero) {
        const { notes } = (await api.zoteroImport(id, zotero.source, zotero.key)).zotero_import
        if (notes.length) toast('warning', notes.map(n => `${n.title}: ${n.note}.`).join(' '))
      }
      step = 'Research saved, but DEIXIS could not start the search: {message}. You can retry from the research page.'
      if (scope !== 'attached') await api.startRun(id, 'discovery', crypto.randomUUID())
      onCreated(id)
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      // The research already exists once created: open it rather than leave the user on a form that looks unsaved.
      if (id) { toast('warning', t(step, { message })); onCreated(id) }
      else setError(message)
    } finally {
      setBusy(false)
    }
  }

  const caption = t(needsFiles
    ? 'Only attached PDFs are used; no academic search runs.'
    : scope === 'attached_and_academic'
      ? 'Connected scholarly providers are searched in addition to your PDFs; the literature model chooses which of them to query.'
      : 'Connected scholarly providers are searched; the literature model chooses which of them to query.')
  const modelName = (id: string) => models.find(m => m.id === id)?.display_name ?? id
  const defaultName = defaults?.reviewer.model ? modelName(defaults.reviewer.model) : null
  const reviewerChoices = [
    { value: DEFAULT_REVIEWER, title: defaultName ? t('Default · {name}', { name: defaultName }) : t('Default · none set'),
      detail: t(defaultName ? 'The reviewer set in Settings for all researches' : 'No reviewer is set in Settings, so answers are not reviewed') },
    { value: NO_REVIEW, title: t('Off'), detail: t('Answers of this research are not reviewed') },
  ]
  const reviewerSummary = reviewer === NO_REVIEW ? t('Off') : reviewer === DEFAULT_REVIEWER ? defaultName ?? t('no reviewer') : modelName(reviewer)

  return <section className="welcome">
    <h1>{uiLanguage() === 'tr' ? <><em>Sorunuz</em> sizi nereye götürüyor?</> : <>Where does your <em>question</em>{' '}lead?</>}</h1>
    <p className="intro">{t('Ask a question. DEIXIS finds publications, lets you choose the sources, and links each claim to a passage you can open.')}</p>
    <form className="composer" onSubmit={e => { e.preventDefault(); void submit() }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void addFiles(e.dataTransfer.files) }}>
      <label className="composer-label" htmlFor="research-question">{t('What would you like to investigate?')}</label>
      <Textarea id="research-question" aria-label={t('Research question')} placeholder={t('How is operations research used in molecular communication?')} value={question}
        onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit() } }} />
      {zoteroOpen && <ZoteroPanel busy={busy} action={t('Use this collection')} onClose={() => setZoteroOpen(false)}
        onImport={(source, key, name) => { setZotero({ source, key, name }); setZoteroOpen(false); if (scope === 'academic') setScope('attached_and_academic') }} />}
      {(files.length > 0 || zotero) && <div className="attachments" aria-label={t('PDFs to attach')}>
        {zotero && <div className="attachment-chip"><button type="button" title={zotero.name}><ConnectionIcon id="zotero" /><span>{zotero.name}</span><small>Zotero</small></button><button type="button" aria-label={t('Remove {name}', { name: zotero.name })} onClick={() => setZotero(null)}><X size={13} /></button></div>}{files.map(file => <div className="attachment-chip" key={file.name}><button type="button" title={file.name}><FileText size={13} /><span>{file.name}</span><small>PDF</small></button><button type="button" aria-label={t('Remove {name}', { name: file.name })} onClick={() => setFiles(old => old.filter(f => f.name !== file.name))}><X size={13} /></button></div>)}</div>}
      <div className="composer-controls">
        <div className="composer-options">
          <DropdownMenu>
            <DropdownMenuTrigger type="button" className="composer-add" aria-label={t('Add sources')} title={t('Add sources (optional)')}><FileUp size={17} /></DropdownMenuTrigger>
            <DropdownMenuContent className="intake-menu" align="start">
              <DropdownMenuGroup>
                <DropdownMenuLabel>{t('ADD SOURCES')}</DropdownMenuLabel>
                <DropdownMenuItem className="intake-menu-item" onClick={() => fileInput.current?.click()}><FileUp size={17} /><span><strong>{t('Upload PDF')}</strong><small>{t('From this computer, up to 50 MB each. You can also drop files here.')}</small></span></DropdownMenuItem>
                <DropdownMenuItem className="intake-menu-item" onClick={() => setZoteroOpen(true)}><ConnectionIcon id="zotero" /><span><strong>{t('Zotero collection')}</strong><small>{t('Read-only, from Zotero on this computer or zotero.org. Imported when the research starts.')}</small></span></DropdownMenuItem>
                <DropdownMenuItem className="intake-menu-item" disabled><BookMarked size={17} /><span><strong>{t('Import BibTeX or RIS')}</strong><small>{t('Not available yet: reference import is not implemented')}</small></span></DropdownMenuItem>
                <DropdownMenuItem className="intake-menu-item" disabled><Link2 size={17} /><span><strong>{t('Add by DOI')}</strong><small>{t('Not available yet: DOI lookup is not implemented')}</small></span></DropdownMenuItem>
                <DropdownMenuItem className="intake-menu-item" disabled><Library size={17} /><span><strong>{t('Add from library')}</strong><small>{t('Not available yet: sources are kept per research')}</small></span></DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <Select value={scope} onValueChange={value => { if (value) setScope(value as SourceScope) }}>
            <SelectTrigger aria-label={t('Source scope')} title={t('Where DEIXIS looks for sources')}><SelectValue>{(value: string) => { const Icon = scopeOptions[value as SourceScope].icon; return <><Icon size={15} />{t(scopeLabels[value as SourceScope])}</> }}</SelectValue></SelectTrigger>
            <SelectContent className="intake-select-content has-details" align="start" alignItemWithTrigger={false}>
              <div className="intake-select-heading" aria-hidden="true">{t('SOURCES')}</div>
                {(Object.keys(scopeLabels) as SourceScope[]).map(s => <SelectItem key={s} value={s}><Option icon={scopeOptions[s].icon} title={t(scopeLabels[s])} detail={t(scopeOptions[s].detail)} /></SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={effort} onValueChange={value => { if (value) setEffort(value as Effort) }}>
            <SelectTrigger aria-label={t('Research depth')} title={t('How much searching and reading a run may do')}><SelectValue>{(value: string) => { const Icon = effortOptions[value as Effort].icon; return <><Icon size={15} />{t(effortLabels[value as Effort])}</> }}</SelectValue></SelectTrigger>
            <SelectContent className="intake-select-content has-details" align="start" alignItemWithTrigger={false}>
              <div className="intake-select-heading" aria-hidden="true">{t('RESEARCH DEPTH')}</div>
                {(Object.keys(effortLabels) as Effort[]).map(d => <SelectItem key={d} value={d}><Option icon={effortOptions[d].icon} title={t(effortLabels[d])} detail={t(effortOptions[d].detail)} /></SelectItem>)}
            </SelectContent>
          </Select>
          {models.length > 0
            ? <button type="button" className="models-summary" aria-expanded={modelsOpen} title={t('Models for this research: answer, literature and reviewer')} onClick={() => setModelsOpen(open => !open)}>
                <span className="models-summary-label">{t('Models')}<span className="sr-only">: </span></span>
                <PenLine size={14} aria-hidden /><span className="models-summary-name">{modelName(model)}</span>
                <ScanSearch size={14} aria-hidden /><span className="models-summary-name">{modelName(literature)}</span>
                <ShieldCheck size={14} aria-hidden /><span className="models-summary-name">{reviewerSummary}</span>
                <ChevronDown size={14} aria-hidden className="models-summary-chevron" />
              </button>
            : <span className="composer-model" title={codex?.reason ?? ''}>{t('Models: {state}', { state: t(connections ? 'Codex not ready' : 'checking…') })}</span>}
        </div>
        <Button className="send-button" type="submit" size="icon" disabled={!question.trim() || busy || !model || !literature || (needsFiles && !files.length && !zotero)} aria-label={t('Start research')}><ArrowUpRight size={20} /></Button>
      </div>
      {modelsOpen && models.length > 0 && <div className="composer-options composer-models">
        <ModelPicker role={t(modelRoles.answer.label)} icon={modelRoles.answer.icon} hint={t(modelRoles.answer.hint)} models={models} value={model}
          onChange={id => chooseModel(id)} effort={reasoning} onEffort={setReasoning} />
        <ModelPicker role={t(modelRoles.literature.label)} icon={modelRoles.literature.icon} hint={t(modelRoles.literature.hint)} models={models} value={literature}
          onChange={id => { setLiterature(id); setLiteratureReasoning(defaultEffort(models, id)) }} effort={literatureReasoning} onEffort={setLiteratureReasoning} />
        <ModelPicker role={t(modelRoles.reviewer.label)} icon={modelRoles.reviewer.icon} hint={t(modelRoles.reviewer.hint)}
          models={models} value={reviewer} onChange={id => { setReviewer(id); setReviewerReasoning(defaultEffort(models, id)) }}
          effort={reviewerReasoning} onEffort={setReviewerReasoning} choices={reviewerChoices} />
        <a className="models-settings-link" href="#/settings">{t('Change the defaults in Settings')}</a>
      </div>}
    </form>
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void addFiles(e.target.files); e.target.value = '' }} />
    <div className="composer-caption"><span>{busy ? t('Saving research…') : caption}</span><span>⌘ / Ctrl + Enter</span></div>
    {codex && !codex.ready && <div className="legacy-boundary">{t('Codex is not ready: {reason}. A research needs a model that Codex lists; model steps pause until the connection is ready, and no other model is used instead.', { reason: codex.reason ?? '' })}</div>}
    {error && <div className="legacy-boundary" role="alert">{error}</div>}
    <div className="resume-section">
      <div className="resume-heading"><h2>{t('Pick up where you left off')}</h2><span>{t('SAVED ON THIS COMPUTER')}</span></div>
      <div className="resume-list">
        {researches.slice(0, 5).map(r => <button key={r.id} onClick={() => onCreated(r.id)}><History size={18} /><span><strong>{r.question}</strong><small>{t(scopeLabels[r.source_scope])} · {t(r.last_run_status ? runStatusLabels[r.last_run_status] : 'No run yet')} · {t(r.answer_count === 1 ? '{n} answer' : '{n} answers', { n: r.answer_count })}</small></span><ArrowUpRight size={16} /></button>)}
        {!researches.length && <p className="empty-inline">{t('No saved research yet.')}</p>}
      </div>
    </div>
  </section>
}
