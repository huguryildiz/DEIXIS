import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, type Connections } from './api'
import { ConnectionIcon } from './connectionIcons'
import { useToast } from './Toast'
import { t } from './i18n'

const modelNames: Record<string, string> = { codex: 'Codex', claude: 'Claude', deepseek: 'DeepSeek', gemini: 'Gemini CLI', kimi: 'Kimi', grok: 'Grok', copilot: 'GitHub Copilot', glm: 'GLM', muse_spark: 'Muse Spark', muse_glimmer: 'Muse Glimmer', ollama: 'Ollama', qwen: 'Qwen', mistral: 'Mistral' }
const providerNames: Record<string, string> = {
  semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', biorxiv: 'bioRxiv', openalex: 'OpenAlex', scopus: 'Scopus', ieee_xplore: 'IEEE Xplore', serpapi: 'SerpApi',
}
const isPlannedModel = (reason?: string | null) => reason === 'Adapter not implemented in this version'
const hasProviderAccessMode = (mode: string | null) => mode === 'api_key' || mode === 'keyless'
const providerStatus = (mode: string | null) => mode === 'api_key' ? t('API key configured') : mode === 'keyless' ? t('No API key required') : t('Key not configured')

type Selected = { kind: 'model' | 'provider'; id: string }

export function ConnectionsPage({ dark }: { dark: boolean }) {
  const [data, setData] = useState<Connections | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // The selection outlives `open` so the drawer keeps its content while it animates closed.
  const [selected, setSelected] = useState<Selected | null>(null)
  const [open, setOpen] = useState(false)
  const load = useCallback((refresh: boolean) => {
    setBusy(true)
    api.connections(refresh).then(result => { setData(result); setError('') }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }, [])
  useEffect(() => { load(false) }, [load])
  const toast = useToast()
  const show = (item: Selected) => { setSelected(item); setOpen(true) }
  const recheck = () => {
    if (!selected) return
    setBusy(true)
    api.connections(true).then(result => {
      setData(result); setError('')
      if (selected.kind === 'model') {
        const m = result.models[selected.id]
        if (m?.ready) toast('success', t('{name}: ready', { name })); else toast('warning', `${name}: ${m?.reason ?? t('not ready')}`)
      } else {
        // This refreshes configuration only; it does not spend a provider request or verify access.
        const p = result.providers.find(x => x.id === selected.id)
        if (p && hasProviderAccessMode(p.access_mode)) toast('success', t('Configuration refreshed; live access was not tested.'))
        else toast('warning', t('{name}: key not configured', { name }))
      }
    }).catch((e: Error) => toast('error', t('Check failed: {message}', { message: e.message }))).finally(() => setBusy(false))
  }
  const isActive = (kind: Selected['kind'], id: string) => open && selected?.kind === kind && selected.id === id
  const check = (label: string, value: string) => <div className="legacy-check" key={label}><span>{label}</span><strong>{value}</strong></div>

  const model = selected?.kind === 'model' ? data?.models[selected.id] : undefined
  const provider = selected?.kind === 'provider' ? data?.providers.find(p => p.id === selected.id) : undefined
  const localTool = selected?.kind === 'local-tool' ? tools?.tools.find(tool => tool.id === selected.id) : undefined
  const name = selected
    ? selected.kind === 'model'
      ? modelNames[selected.id] ?? selected.id
      : selected.kind === 'provider'
        ? providerNames[selected.id] ?? selected.id
        : localTool?.name || localToolNames[selected.id] || selected.id
    : ''
  const modelEntries = Object.entries(data?.models ?? {})
  const availableModels = modelEntries.filter(([, model]) => !isPlannedModel(model.reason))
  const plannedModels = modelEntries.filter(([, model]) => isPlannedModel(model.reason))
  const modelCard = ([id, m]: (typeof modelEntries)[number]) => <button type="button" className={`connection-card ${m.ready ? 'is-ready' : ''} ${isActive('model', id) ? 'active' : ''}`} key={id} onClick={() => show({ kind: 'model', id })}><div className="connection-card-head"><ConnectionIcon id={id} /><strong>{modelNames[id] ?? id}</strong></div>{m.ready ? <span className="status-chip">{t('Ready')}</span> : <small>{m.reason ?? t('Not ready')}</small>}</button>

  const openaiKey = credentials?.keys.find(k => k.env === 'OPENAI_API_KEY')
  const geminiKey = credentials?.keys.find(k => k.env === 'GEMINI_API_KEY')

  const cliTools = (tools?.tools ?? []).filter(tool => tool.kind === 'cli')
  const serverTools = (tools?.tools ?? []).filter(tool => tool.kind === 'server')
  const machine = tools?.machine
  const hasMachineInfo = machine && (machine.chip || machine.memory_gb != null || machine.disk_free_gb != null)

  const semanticLabels: Record<SemanticSearchProvider, string> = { gemini: 'Gemini', openai: 'OpenAI', ollama: t('This computer · Ollama'), lm_studio: t('This computer · LM Studio'), off: t('Off · keyword search only') }
  const needsModel = (p: SemanticSearchProvider | null) => p === 'ollama' || p === 'lm_studio'
  function chooseSemantic(p: SemanticSearchProvider, models: string[]) { setSemProvider(p); setSemModel(needsModel(p) ? (models[0] ?? null) : null) }
  function saveSemantic() {
    if (!semProvider) return
    setSemBusy(true)
    api.saveSemanticSearch(semProvider, needsModel(semProvider) ? semModel : null)
      .then(result => { setSemantic(result); toast('success', t('Semantic search setting saved.')) })
      .catch((e: Error) => toast('error', t('Could not save: {message}', { message: e.message })))
      .finally(() => setSemBusy(false))
  }

  return <div className="connections-tab">
    {error && <div className="legacy-boundary">{error}</div>}

    <section className="connections-group">
      <h2 className="with-icon"><Cloud size={20} aria-hidden />{t('Cloud models')}</h2>
      <p className="legacy-mini-note">{t('Passages are sent to the provider you choose. Once a key is saved it is never shown again; it can only be replaced or removed.')}</p>
      <div className="legacy-connection-cards available-model-connections">
        {availableModels.map(modelCard)}
        <article className="connection-card openai-card">
          <div className="connection-card-head"><ConnectionIcon id="openai" /><strong>{t('OpenAI API')}</strong></div>
          {openaiKey && (openaiKey.configured ? <span className="status-chip">{t('Key configured')}</span> : <small>{t('Not connected')}</small>)}
          {credentials && <KeyPanel env="OPENAI_API_KEY" entry={openaiKey} keychain={credentials.keychain} dark={dark} onSaved={reloadAfterKeyChange} />}
        </article>
      </div>
      {plannedModels.length > 0 && <details className="planned-connections"><summary>{t('Planned model connections · {n}', { n: plannedModels.length })}</summary><div className="legacy-connection-cards">{plannedModels.map(modelCard)}</div></details>}
    </section>

    <section className="connections-group">
      <h2 className="with-icon"><Laptop size={20} aria-hidden />{t('On this computer')}</h2>
      <p className="legacy-mini-note">{t('Found from this computer’s PATH, installed apps and local server ports. Install runs the command shown, after you confirm.')}</p>
      {hasMachineInfo && <p className="local-tool-machine">
        {machine?.chip && <span>{t('This computer: {chip}', { chip: machine.chip })}</span>}
        {machine?.memory_gb != null && <span>{t('Memory: {gb} GB', { gb: machine.memory_gb })}</span>}
        {machine?.disk_free_gb != null && <span>{t('Free disk: {gb} GB', { gb: machine.disk_free_gb })}</span>}
      </p>}
      {toolsError && <div className="legacy-boundary">{toolsError}</div>}
      <h3 className="connections-subhead with-icon"><SquareTerminal size={15} aria-hidden />{t('Command-line tools')}</h3>
      <div className="local-tool-pills">{cliTools.map(tool => <button type="button" className={`local-tool-pill ${tool.installed ? 'is-ready' : ''} ${isActive('local-tool', tool.id) ? 'active' : ''}`} key={tool.id} onClick={() => show({ kind: 'local-tool', id: tool.id })}><ConnectionIcon id={localToolIcon(tool.id)} /><strong>{tool.name || localToolNames[tool.id] || tool.id}</strong><span className="local-tool-pill-status">{t(tool.installed ? 'Installed' : 'Not installed')}</span></button>)}</div>
      <h3 className="connections-subhead with-icon"><Server size={15} aria-hidden />{t('Local model servers')}</h3>
      <div className="local-tool-pills">{serverTools.map(tool => <button type="button" className={`local-tool-pill ${tool.installed ? 'is-ready' : ''} ${isActive('local-tool', tool.id) ? 'active' : ''}`} key={tool.id} onClick={() => show({ kind: 'local-tool', id: tool.id })}><ConnectionIcon id={localToolIcon(tool.id)} /><strong>{tool.name || localToolNames[tool.id] || tool.id}</strong><span className="local-tool-pill-status">{t(tool.installed ? 'Installed' : 'Not installed')}</span></button>)}</div>
      <p className="legacy-mini-note">{t('Local models do not run research steps in this version; embedding models can be chosen for semantic search.')}</p>
    </section>

    <section className="connections-group">
      <h2 className="with-icon"><Sparkles size={20} aria-hidden />{t('Semantic search')}</h2>
      <p className="legacy-mini-note">{t('The question and passages are matched by meaning even when the words differ, and the result is fused with keyword search. Changing the provider embeds passages again; earlier vectors are kept. Similarity only ranks passages; it does not show that a passage supports a claim.')}</p>
      {semError && <div className="legacy-boundary">{semError}</div>}
      {semantic && <>
        <div className="semantic-choices" role="radiogroup" aria-label={t('Semantic search provider')}>
          {semantic.options.map(opt => {
            const checked = semProvider === opt.provider
            return <label className={`semantic-choice ${!opt.available ? 'is-disabled' : ''}`} key={opt.provider}>
              <input type="radio" name="semantic-provider" checked={checked} disabled={!opt.available} onChange={() => chooseSemantic(opt.provider, opt.models)} />
              {opt.provider === 'off' ? <TextSearch className="semantic-off-icon" size={16} aria-hidden /> : <ConnectionIcon id={opt.provider} />}
              <strong>{semanticLabels[opt.provider]}</strong>
              {!needsModel(opt.provider) && opt.models[0] && <code className="semantic-model-name">{opt.models[0]}</code>}
              {opt.available ? <span className="status-chip">{t('Available')}</span> : <span className="semantic-reason">{t(opt.reason ?? '')}</span>}
              {needsModel(opt.provider) && checked && <select className="semantic-model" value={semModel ?? ''} onChange={e => setSemModel(e.target.value)}>{opt.models.map(m => <option key={m} value={m}>{m}</option>)}</select>}
            </label>
          })}
        </div>
        {semProvider && <p className="legacy-mini-note">{semProvider === 'off' ? t('Passages are ranked by keyword match only; no text is sent anywhere.') : semProvider === 'gemini' ? t('Passage text is sent to {service}.', { service: 'Google' }) : semProvider === 'openai' ? t('Passage text is sent to {service}.', { service: 'OpenAI' }) : t('Passage text stays on this computer.')}</p>}
        <div className="actions"><Button size="sm" disabled={semBusy || !semProvider || (needsModel(semProvider) && !semModel)} onClick={saveSemantic}>{t(semBusy ? 'Saving…' : 'Save')}</Button></div>
      </>}
    </section>

    <section className="connections-group">
      <h2 className="with-icon"><GraduationCap size={20} aria-hidden />{t('Scholarly sources')}</h2>
      <div className="legacy-connection-cards">{data?.providers.map(p => <button type="button" className={`connection-card ${p.access_mode === 'api_key' ? 'is-key-configured' : ''} ${isActive('provider', p.id) ? 'active' : ''}`} key={p.id} onClick={() => show({ kind: 'provider', id: p.id })}><div className="connection-card-head"><ConnectionIcon id={p.id} /><strong>{providerNames[p.id] ?? p.id}</strong></div>{hasProviderAccessMode(p.access_mode) ? <span className={`status-chip ${p.access_mode === 'keyless' ? 'is-configured' : ''}`}>{providerStatus(p.access_mode)}</span> : <small>{providerStatus(p.access_mode)}</small>}</button>)}</div>
      <p className="legacy-mini-note">{t('Every provider with the access it needs is enabled for new researches, and the model chooses which to query. Access and remaining quota are recorded with each request rather than guaranteed in advance.')}</p>
    </section>

    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet source-sheet connection-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader><SheetTitle>{t(selected?.kind === 'provider' ? 'Scholarly source' : selected?.kind === 'local-tool' ? 'Local tool details' : 'Model connection')}</SheetTitle><SheetDescription className="sr-only">{t('{name} details', { name })}</SheetDescription></SheetHeader>
        <div className="sheet-body">
          {selected && <div className="connection-sheet-head"><ConnectionIcon id={selected.kind === 'local-tool' ? localToolIcon(selected.id) : selected.id} /><h2 className="source-title">{name}</h2></div>}
          {localTool && <LocalToolDetails key={localTool.id} tool={localTool} dark={dark} onChanged={() => loadTools(true)} />}
          {model && <>
            {model.ready ? <span className="status-chip">{t('Ready')}</span> : <p className="source-byline">{model.reason ?? t('Not ready')}</p>}
            {selected?.id === 'codex' && <>
              <p className="source-byline">{t('DEIXIS runs Codex in its own Codex home with tools, connectors, skills and instruction files disabled, and starts a new session for every step.')}</p>
              <div className="connection-checks">
                {check('CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
                {check(t('Signed in (DEIXIS Codex home)'), model.signed_in ? t('yes · {plan}', { plan: model.plan_type ?? model.account_type ?? '' }) : t('no'))}
                {check(t('Instruction files loaded'), model.isolation ? String(model.isolation.instruction_sources) : t('not checked'))}
                {check(t('MCP servers with tools'), model.isolation ? (model.isolation.live_mcp_servers.join(', ') || t('none')) : t('not checked'))}
              </div>
              {!model.signed_in && model.installed && <p className="source-byline">{t('Sign in once in a terminal:')}<br /><code className="command">CODEX_HOME="$HOME/Library/Application Support/DEIXIS/codex-home" codex login</code></p>}
              <h3 className="source-section">{t('Models listed · {n}', { n: model.models?.length ?? 0 })}</h3>
              {model.models && model.models.length > 0 && <ul className="connection-models">{model.models.map(m => <li key={m.id}><span>{m.display_name}</span>{m.is_default && <small>{t('default')}</small>}</li>)}</ul>}
            </>}
            {selected?.id === 'gemini' && <>
              <p className="source-byline">{t('DEIXIS calls the Gemini API directly with GEMINI_API_KEY, with no tools, instruction files or CLI agent prompt, and one new request per step. The Gemini CLI is only detected; it does not run steps.')}</p>
              <div className="connection-checks">
                {check(t('API key (GEMINI_API_KEY)'), model.key_configured ? t('set') : t('not set'))}
                {check('Gemini CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
                {check(t('Semantic passage search'), model.key_configured ? t('on · passage text is sent to Google') : t('off'))}
              </div>
              {credentials && <KeyPanel env="GEMINI_API_KEY" entry={geminiKey} keychain={credentials.keychain} dark={dark} onSaved={reloadAfterKeyChange} />}
              <h3 className="source-section">{t('Models listed · {n}', { n: model.models?.length ?? 0 })}</h3>
              {model.models && model.models.length > 0 && <ul className="connection-models">{model.models.map(m => <li key={m.id}><span>{m.display_name}</span></li>)}</ul>}
            </>}
          </>}
          {provider && <>
            {hasProviderAccessMode(provider.access_mode) && <span className={`status-chip ${provider.access_mode === 'keyless' ? 'is-configured' : ''}`}>{providerStatus(provider.access_mode)}</span>}
            <p className="source-byline">{provider.note}</p>
            <div className="connection-checks">{check(t('Access mode'), provider.access_mode ? t(provider.access_mode) : t('none'))}</div>
            {credentials && providerKeyEnv[provider.id] && <KeyPanel env={providerKeyEnv[provider.id]} entry={credentials.keys.find(k => k.env === providerKeyEnv[provider.id])} keychain={credentials.keychain} dark={dark} onSaved={reloadAfterKeyChange} />}
          </>}
          {!localTool && <Button variant="outline" className="connection-recheck" onClick={recheck} disabled={busy}><RefreshCw size={14} />{t(provider ? (busy ? 'Refreshing…' : 'Refresh configuration') : (busy ? 'Checking…' : 'Check again'))}</Button>}
        </div>
      </SheetContent>
    </Sheet>
  </div>
}
