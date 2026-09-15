import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Popover } from '@base-ui/react/popover'
import { ArrowUpRight, BookMarked, Brain, Check, ChevronDown, FileText, FileUp, Gauge, Globe, History, Layers, Library, Paperclip, PenLine, ScanSearch, Search, ShieldCheck, Telescope, X, Zap, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from './Toast'
import { api, type Connections, type Effort, type ModelOption, type ModelRole, type ResearchSummary, type RoleModelSetting, type SourceScope, type ZoteroSource } from './api'
import { connectionName, isPlannedModel, reasoningLabel, runStatusLabels, scopeLabels } from './labels'
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

// Gemini CLI has no user-facing effort control. Keep its internal API thinking configuration out of the UI and requests.
type SelectableModel = ModelOption & { connection?: string }
const exposesEffortControl = (model: SelectableModel | undefined) => model?.connection !== 'gemini'

// Each model with a user-facing effort control starts from the model's declared default.
export const defaultEffort = (models: SelectableModel[], id: string) => {
  const m = models.find(x => x.id === id)
  if (!exposesEffortControl(m)) return null
  return m?.default_reasoning_effort ?? null
}
const listedEffort = (models: SelectableModel[], id: string, effort: string | null) => {
  const model = models.find(m => m.id === id)
  return exposesEffortControl(model) && model?.reasoning_efforts?.some(e => e.id === effort) ? effort : null
}

// The models of every connection in one list. An entry's id is `connection:model`, so each role can pick from any connection.
export type ConnectionModel = ModelOption & { connection: string; model: string }
export const modelKey = (connection: string, model: string) => `${connection}:${model}`
export const connectionModels = (connections: Connections): ConnectionModel[] =>
  Object.entries(connections.models).flatMap(([connection, health]) => (health.models ?? []).map(m => ({ ...m, id: modelKey(connection, m.id), connection, model: m.id })))
// Why implemented connections offer no model.
export const notReadyReasons = (connections: Connections) =>
  Object.values(connections.models).filter(h => !h.ready && !isPlannedModel(h.reason)).map(h => `${connectionName(h.connection)}: ${h.reason ?? ''}`).join('; ')

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
  role: string; icon: LucideIcon; hint: string; models: ConnectionModel[]; value: string; onChange: (value: string) => void
  effort: string | null; onEffort: (effort: string | null) => void; choices?: { value: string; title: string; detail: string }[]
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeValue, setActiveValue] = useState(value)
  const searchRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const chosen = models.find(m => m.id === value)
  const efforts = exposesEffortControl(chosen) ? chosen?.reasoning_efforts ?? [] : []
  const name = (v: string) => choices.find(c => c.value === v)?.title ?? models.find(m => m.id === v)?.display_name ?? v
  const normalizedQuery = query.trim().toLocaleLowerCase(uiLocale())
  const matches = (...parts: Array<string | null | undefined>) => !normalizedQuery || parts.some(part => part?.toLocaleLowerCase(uiLocale()).includes(normalizedQuery))
  const visibleChoices = choices.filter(choice => matches(choice.title, choice.detail))
  const visibleModels = models.filter(model => matches(model.display_name, model.description, connectionName(model.connection)))
  const groups = [...new Set(visibleModels.map(model => model.connection))]
  const entries = [
    ...visibleChoices.map(choice => ({ value: choice.value, title: choice.title, detail: choice.detail, connection: null as string | null, isDefault: false })),
    ...visibleModels.map(model => ({ value: model.id, title: model.display_name, detail: model.description ?? '', connection: model.connection, isDefault: Boolean(model.is_default) })),
  ]
  const active = entries.find(entry => entry.value === activeValue) ?? entries.find(entry => entry.value === value) ?? entries[0]

  const choose = (next: string) => {
    onChange(next)
    setOpen(false)
  }
  const move = (direction: 1 | -1) => {
    if (!entries.length) return
    const current = entries.findIndex(entry => entry.value === active?.value)
    const next = (current + direction + entries.length) % entries.length
    setActiveValue(entries[next].value)
    requestAnimationFrame(() => document.getElementById(`${listId}-${next}`)?.scrollIntoView({ block: 'nearest' }))
  }
  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      move(event.key === 'ArrowDown' ? 1 : -1)
    } else if (event.key === 'Enter' && active) {
      event.preventDefault()
      choose(active.value)
    }
  }
  const optionId = (optionValue: string) => {
    const index = entries.findIndex(entry => entry.value === optionValue)
    return index < 0 ? undefined : `${listId}-${index}`
  }
  const option = (optionValue: string, title: string, detail: string, connection: string | null, isDefault = false) => (
    <button id={optionId(optionValue)} type="button" role="option" aria-selected={optionValue === value}
      className={`model-palette-option ${optionValue === active?.value ? 'is-active' : ''}`}
      onMouseMove={() => setActiveValue(optionValue)} onFocus={() => setActiveValue(optionValue)} onClick={() => choose(optionValue)}>
      <span className="model-palette-option-icon">{connection ? <ConnectionIcon id={connection} /> : <Icon size={16} />}</span>
      <span className="model-palette-option-copy"><strong>{title}</strong><small>{detail}</small></span>
      {isDefault && <span className="model-palette-badge">{t('Default')}</span>}
      <Check className="model-palette-check" size={15} aria-hidden />
    </button>
  )
  return <div className="model-role">
    <Popover.Root open={open} onOpenChange={next => { setOpen(next); if (next) { setQuery(''); setActiveValue(value) } }}>
      <Popover.Trigger data-slot="select-trigger" className="model-picker-trigger" aria-label={t('{role} model', { role })} title={hint}>
        <Icon size={15} /><span className="model-role-name">{role}</span><span className="model-picker-value">{name(value)}</span><ChevronDown size={14} className="model-picker-chevron" aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Backdrop className="model-palette-backdrop" />
        <Popover.Positioner className="model-palette-positioner" side="bottom" align="start" sideOffset={8} collisionPadding={14}>
          <Popover.Popup className="model-palette" initialFocus={searchRef}>
            <div className="model-palette-header">
              <Popover.Title className="model-palette-title">{t('{role} MODEL', { role: role.toLocaleUpperCase(uiLocale()) })}</Popover.Title>
              <Popover.Description className="model-palette-description">{hint}</Popover.Description>
              <label className="model-palette-search">
                <Search size={16} aria-hidden /><span className="sr-only">{t('Search models or providers')}</span>
                <input ref={searchRef} value={query} onChange={event => { setQuery(event.target.value); setActiveValue('') }}
                  onKeyDown={onSearchKeyDown} placeholder={t('Search models or providers')} role="combobox" aria-expanded="true"
                  aria-controls={listId} aria-activedescendant={active ? optionId(active.value) : undefined} autoComplete="off" />
              </label>
            </div>
            <div id={listId} className="model-palette-list" role="listbox" aria-label={t('{role} model', { role })}>
              {visibleChoices.length > 0 && <section className="model-palette-group" aria-label={t('Options')}>
                <div className="model-palette-group-label">{t('Options')}</div>
                {visibleChoices.map(choice => option(choice.value, choice.title, choice.detail, null))}
              </section>}
              {groups.map(connection => <section className="model-palette-group" aria-label={connectionName(connection)} key={connection}>
                <div className="model-palette-group-label"><ConnectionIcon id={connection} /><span>{connectionName(connection)}</span><small>{visibleModels.filter(model => model.connection === connection).length}</small></div>
                {visibleModels.filter(model => model.connection === connection).map(model => option(model.id, model.display_name, model.description ?? '', model.connection, Boolean(model.is_default)))}
              </section>)}
              {entries.length === 0 && <div className="model-palette-empty"><Search size={17} aria-hidden /><span>{t('No models match “{query}”', { query })}</span></div>}
            </div>
            {active && <div className="model-palette-preview" aria-live="polite">
              <span>{active.connection ? connectionName(active.connection) : role}{active.isDefault ? ` · ${t('Default')}` : ''}</span>
              <strong>{active.title}</strong>
              {active.detail && <p>{active.detail}</p>}
              <small>{t('Press Enter to select')}</small>
            </div>}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
    {efforts.length > 0 &&
      <Select value={effort ?? '__provider_default'} onValueChange={v => { if (v) onEffort(v === '__provider_default' ? null : v) }}>
        <SelectTrigger aria-label={t('{role} reasoning effort', { role })} title={t('How long the {role} model thinks', { role: role.toLocaleLowerCase(uiLocale()) })}><SelectValue>{(v: string) => <><Brain size={15} />{reasoningLabel(v)}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content has-details" align="start" alignItemWithTrigger={false}>
          <div className="intake-select-heading" aria-hidden="true">{t('{role} REASONING EFFORT', { role: role.toLocaleUpperCase(uiLocale()) })}</div>
          <p className="intake-select-description" aria-hidden="true">{t('How long the {role} model reasons before it replies. Higher settings take longer.', { role: role.toLocaleLowerCase(uiLocale()) })}</p>
          <SelectItem value="__provider_default"><Option icon={Brain} title={t('Provider default')} detail={t('Let the current model choose its default effort')} /></SelectItem>
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
      const models = connectionModels(result)
      const preferred = models.find(m => m.is_default) ?? models[0]
      // A default from Settings applies while its connection still lists it; otherwise the composer starts from Codex's default model.
      const start = (setting: RoleModelSetting | undefined) => {
        const saved = setting?.model ? modelKey(setting.model_connection, setting.model) : null
        const id = saved && models.some(m => m.id === saved) ? saved : preferred?.id
        if (!id) return null
        return { id, effort: (id === saved ? listedEffort(models, id, setting?.reasoning_effort ?? null) : null) ?? defaultEffort(models, id) }
      }
      const answer = start(saved?.answer)
      const literature = start(saved?.literature)
      if (answer) { setModel(answer.id); setReasoning(answer.effort) }
      if (literature) { setLiterature(literature.id); setLiteratureReasoning(literature.effort) }
    }).catch((e: Error) => setError(t('Could not read connections: {message}', { message: e.message })))
  }, [])

  const models = connections ? connectionModels(connections) : []
  const chosen = models.find(m => m.id === model)
  const efforts = chosen?.reasoning_efforts ?? []
  const needsFiles = scope === 'attached'

  function chooseModel(id: string, list = models) {
    const next = list.find(m => m.id === id)
    setModel(id)
    // Each model lists its own efforts; use the provider-declared default when one exists.
    setReasoning(next?.default_reasoning_effort ?? null)
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
    const literatureChoice = models.find(m => m.id === literature)
    if (!chosen || !literatureChoice) { setError(t('Choose the answer and literature models first. DEIXIS does not pick them for you.')); return }
    setBusy(true)
    setError('')
    let id: string | null = null
    let step = ''
    const customReviewer = reviewer !== DEFAULT_REVIEWER && reviewer !== NO_REVIEW
    const reviewerChoice = customReviewer ? models.find(m => m.id === reviewer) : undefined
    try {
      const view = await api.create({ question: question.trim(), source_scope: scope, effort, model_connection: chosen.connection, requested_model: chosen.model,
        reasoning_effort: efforts.some(e => e.id === reasoning) ? reasoning : null,
        literature_connection: literatureChoice.connection, literature_model: literatureChoice.model,
        literature_reasoning_effort: listedEffort(models, literature, literatureReasoning),
        review_mode: customReviewer ? 'custom' : reviewer === NO_REVIEW ? 'off' : 'default',
        review_connection: reviewerChoice?.connection ?? null, review_model: reviewerChoice?.model ?? null,
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
  const modelName = (id: string) => models.find(m => m.id === id)?.display_name ?? id.slice(id.indexOf(':') + 1)
  const defaultName = defaults?.reviewer.model ? modelName(modelKey(defaults.reviewer.model_connection, defaults.reviewer.model)) : null
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
                <DropdownMenuItem className="intake-menu-item" disabled><ConnectionIcon id="doi" /><span><strong>{t('Add by DOI')}</strong><small>{t('Not available yet: DOI lookup is not implemented')}</small></span></DropdownMenuItem>
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
            : <span className="composer-model" title={connections ? notReadyReasons(connections) : ''}>{t('Models: {state}', { state: t(connections ? 'no connection ready' : 'checking…') })}</span>}
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
    {connections && !models.length && <div className="legacy-boundary">{t('No model connection is ready: {reason}. A research needs a model that a connection lists; model steps pause until the chosen connection is ready, and no other model is used instead.', { reason: notReadyReasons(connections) })}</div>}
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
