import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type Connections } from './api'

const modelNames: Record<string, string> = { codex: 'Codex', claude: 'Claude', deepseek: 'DeepSeek' }
const providerNames: Record<string, string> = {
  semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', openalex: 'OpenAlex', scopus: 'Scopus', ieee_xplore: 'IEEE Xplore', serpapi: 'SerpApi',
}

export function ConnectionsPage() {
  const [data, setData] = useState<Connections | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = useCallback((refresh: boolean) => {
    setBusy(true)
    api.connections(refresh).then(result => { setData(result); setError('') }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }, [])
  useEffect(() => { load(false) }, [load])
  const codex = data?.models.codex
  const check = (label: string, value: string) => <div className="legacy-check" key={label}><span>{label}</span><strong>{value}</strong></div>

  return <section className="collection legacy-connections">
    <div className="section-label">CONNECTIONS</div>
    <h1>Connections</h1>
    <p>Model and literature sources are selected separately. DEIXIS does not switch either one after a failure.</p>
    {error && <div className="legacy-boundary">{error}</div>}
    <div className="legacy-connection-grid">
      <div>
        <h2>Model connections</h2>
        <div className="legacy-connection-cards">{data && Object.entries(data.models).map(([id, m]) => <div className={`connection-card ${m.ready ? 'is-ready' : ''}`} key={id}><strong>{modelNames[id] ?? id}</strong><small>{m.ready ? 'Ready' : m.reason ?? 'Not ready'}</small></div>)}</div>
        <h2>Scholarly sources</h2>
        <div className="legacy-connection-cards">{data?.providers.map(p => <div className={`connection-card ${p.implemented ? 'is-ready' : ''}`} key={p.id}><strong>{providerNames[p.id] ?? p.id}</strong><small>{p.implemented ? `Connected · ${p.access_mode}` : 'Not implemented yet'}</small></div>)}</div>
        <p className="legacy-mini-note">All seven providers remain in scope; this version implements OpenAlex only. OpenAlex access and remaining quota are recorded with each request rather than guaranteed in advance.</p>
      </div>
      <aside>
        <div className="section-label">CODEX DETAILS</div>
        <h2>Codex</h2>
        <p>DEIXIS runs Codex in its own Codex home with tools, connectors, skills and instruction files disabled, and starts a new session for every step.</p>
        {codex && <>
          {check('CLI', codex.installed ? codex.cli_version ?? 'installed' : 'not found')}
          {check('Signed in (DEIXIS Codex home)', codex.signed_in ? `yes · ${codex.plan_type ?? codex.account_type ?? ''}` : 'no')}
          {check('Instruction files loaded', codex.isolation ? String(codex.isolation.instruction_sources) : 'not checked')}
          {check('MCP servers with tools', codex.isolation ? (codex.isolation.live_mcp_servers.join(', ') || 'none') : 'not checked')}
          {check('Models listed', String(codex.models?.length ?? 0))}
          {!codex.signed_in && codex.installed && <p>Sign in once in a terminal:<br /><code className="command">CODEX_HOME="$HOME/Library/Application Support/DEIXIS/codex-home" codex login</code></p>}
        </>}
        <Button variant="outline" onClick={() => load(true)} disabled={busy}><RefreshCw size={14} />{busy ? 'Checking…' : 'Check again'}</Button>
      </aside>
    </div>
  </section>
}
