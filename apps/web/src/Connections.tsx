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
  const name = selected ? (selected.kind === 'model' ? modelNames : providerNames)[selected.id] ?? selected.id : ''
  const modelEntries = Object.entries(data?.models ?? {})
  const availableModels = modelEntries.filter(([, model]) => !isPlannedModel(model.reason))
  const plannedModels = modelEntries.filter(([, model]) => isPlannedModel(model.reason))
  const modelCard = ([id, m]: (typeof modelEntries)[number]) => <button type="button" className={`connection-card ${m.ready ? 'is-ready' : ''} ${isActive('model', id) ? 'active' : ''}`} key={id} onClick={() => show({ kind: 'model', id })}><div className="connection-card-head"><ConnectionIcon id={id} /><strong>{modelNames[id] ?? id}</strong></div>{m.ready ? <span className="status-chip">{t('Ready')}</span> : <small>{m.reason ?? t('Not ready')}</small>}</button>

  return <section className="collection legacy-connections">
    <div className="section-label">{t('CONNECTIONS')}</div>
    <h1>{t('Connections')}</h1>
    <p>{t('Model and literature sources are selected separately. DEIXIS does not switch either one after a failure.')}</p>
    {error && <div className="legacy-boundary">{error}</div>}
    <div className="legacy-connection-grid">
      <h2>{t('Model connections')}</h2>
      <div className="legacy-connection-cards available-model-connections">{availableModels.map(modelCard)}</div>
      {plannedModels.length > 0 && <details className="planned-connections"><summary>{t('Planned model connections · {n}', { n: plannedModels.length })}</summary><div className="legacy-connection-cards">{plannedModels.map(modelCard)}</div></details>}
      <h2>{t('Scholarly sources')}</h2>
      <div className="legacy-connection-cards">{data?.providers.map(p => <button type="button" className={`connection-card ${p.access_mode === 'api_key' ? 'is-key-configured' : ''} ${isActive('provider', p.id) ? 'active' : ''}`} key={p.id} onClick={() => show({ kind: 'provider', id: p.id })}><div className="connection-card-head"><ConnectionIcon id={p.id} /><strong>{providerNames[p.id] ?? p.id}</strong></div>{hasProviderAccessMode(p.access_mode) ? <><span className={`status-chip ${p.access_mode === 'keyless' ? 'is-configured' : ''}`}>{providerStatus(p.access_mode)}</span>{p.supplementary && <small>{t('Supplementary coverage only')}</small>}</> : <small>{providerStatus(p.access_mode)}</small>}</button>)}</div>
      <p className="legacy-mini-note">{t('Every provider with the access it needs is enabled for new researches, and the model chooses which to query. Access and remaining quota are recorded with each request rather than guaranteed in advance.')}</p>
    </div>

    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet source-sheet connection-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader><SheetTitle>{t(selected?.kind === 'provider' ? 'Scholarly source' : 'Model connection')}</SheetTitle><SheetDescription className="sr-only">{t('{name} details', { name })}</SheetDescription></SheetHeader>
        <div className="sheet-body">
          {selected && <div className="connection-sheet-head"><ConnectionIcon id={selected.id} /><h2 className="source-title">{name}</h2></div>}
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
          </>}
          {provider && <>
            {hasProviderAccessMode(provider.access_mode) && <span className={`status-chip ${provider.access_mode === 'keyless' ? 'is-configured' : ''}`}>{providerStatus(provider.access_mode)}</span>}
            <p className="source-byline">{provider.note}</p>
            <div className="connection-checks">{check(t('Access mode'), provider.access_mode ? t(provider.access_mode) : t('none'))}</div>
          </>}
          <Button variant="outline" className="connection-recheck" onClick={recheck} disabled={busy}><RefreshCw size={14} />{t(provider ? (busy ? 'Refreshing…' : 'Refresh configuration') : (busy ? 'Checking…' : 'Check again'))}</Button>
        </div>
      </SheetContent>
    </Sheet>
  </section>
}
