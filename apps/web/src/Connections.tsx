import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { BookMarked, Cloud, GraduationCap, Laptop, LoaderCircle, RefreshCw, ScanText, Server, Sigma, Sparkles, SquareTerminal, TextSearch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ConfirmDialog } from './ConfirmDialog'
import { api, type BuiltinEmbedding, type Connections, type Credentials, type KeyEntry, type Keychain, type EquationReader, type LocalTool, type OcrTool, type LocalTools, type ModelHealth, type SemanticSearch, type SemanticSearchOption, type SemanticSearchProvider } from './api'
import { ConnectionIcon } from './connectionIcons'
import { useToast } from './Toast'
import { ocrLanguagesText } from './ocr'
import { t, uiLocale } from './i18n'
import { connectionNames as modelNames, isPlannedModel, localToolIcon, localToolNames, providerRole, reasoningLabel } from './labels'
import { Notice } from './Notice'

const providerNames: Record<string, string> = {
  semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', biorxiv: 'bioRxiv', pubmed: 'PubMed', openalex: 'OpenAlex', scopus: 'Scopus', ieee_xplore: 'IEEE Xplore', core: 'CORE', serpapi: 'SerpApi',
}
// Providers that take their own key; env names come from the credentials contract.
const providerKeyEnv: Record<string, string> = { openalex: 'OPENALEX_API_KEY', biorxiv: 'OPENALEX_API_KEY', semantic_scholar: 'S2_API_KEY', pubmed: 'NCBI_API_KEY', ieee_xplore: 'IEEE_API_KEY', scopus: 'SCOPUS_API_KEY', core: 'CORE_API_KEY', serpapi: 'SERPAPI_API_KEY' }
const hasProviderAccessMode = (mode: string | null) => mode === 'api_key' || mode === 'keyless'
const providerStatus = (mode: string | null) => mode === 'api_key' ? t('API key configured') : mode === 'keyless' ? t('No API key required') : t('Key not configured')
const formatBytes = (bytes: number) => bytes / 1e9 >= 1 ? t('{gb} GB', { gb: (bytes / 1e9).toFixed(1) }) : t('{mb} MB', { mb: Math.round(bytes / 1e6) })

type Selected = { kind: 'model' | 'provider' | 'local-tool' | 'equation-reader' | 'ocr-tool' | 'api-key'; id: string }

// One connection in a grid: icon, name and a status line with a dot, green when it can be used.
function ConnectionTile({ icon, name, ok, status, active, onClick }: { icon: ReactNode; name: string; ok: boolean; status: string; active: boolean; onClick: () => void }) {
  return <button type="button" className={`connection-card ${ok ? 'is-ready' : ''} ${active ? 'active' : ''}`} onClick={onClick}>
    <span className="connection-card-icon">{icon}</span>
    <span className="connection-card-text"><strong>{name}</strong><span className="connection-card-status" title={status}>{status}</span></span>
  </button>
}

// Shared key management block: status + test/replace/remove, or the key form. Used for cloud model
// keys (Gemini, OpenAI) and scholarly source keys inside their respective cards/sheets.
function KeyPanel({ env, entry, keychain, dark, onSaved }: { env: string; entry: KeyEntry | undefined; keychain: Keychain; dark: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [formError, setFormError] = useState('')
  const [confirmRemove, setConfirmRemove] = useState(false)
  const toast = useToast()
  if (!entry) return null
  const id = `key-${env}`

  const inDotenv = entry.source === 'dotenv'
  if (entry.source === 'environment') return <p>{t('This key is set in the shell that started DEIXIS; change or remove it there.')}</p>

  function test() {
    setTesting(true)
    api.testCredential(env).then(result => {
      toast(result.status === 'ok' ? 'success' : 'warning', result.detail)
      onSaved()
    }).catch((e: Error) => toast('error', e.message)).finally(() => setTesting(false))
  }
  function save() {
    setBusy(true); setFormError('')
    api.saveCredential(env, value).then(() => { setEditing(false); setValue(''); onSaved(); toast('success', t('Key saved.')) })
      .catch((e: Error) => setFormError(e.message)).finally(() => setBusy(false))
  }
  function remove() {
    setBusy(true)
    api.removeCredential(env).then(() => { setConfirmRemove(false); onSaved(); toast('success', t('Key removed.')) })
      .catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }

  if (editing) return <form className="key-form" onSubmit={e => { e.preventDefault(); save() }}>
    <label htmlFor={id}>{t('API key')}</label>
    <input id={id} className="key-field" type="password" autoComplete="off" value={value} onChange={e => setValue(e.target.value)} />
    <p className="key-form-note">{inDotenv
      ? t(entry.testable ? 'The key is tested with one short request before it is saved. It replaces the line in .env and is never shown again.' : 'It replaces the line in .env and is never shown again.')
      : t(entry.testable ? 'The key is tested with one short request before it is saved. It is stored in {keychain} and never shown again.' : 'It is stored in {keychain} and never shown again.', { keychain: keychain.name ?? t('the system keychain') })}</p>
    {formError && <p className="key-form-error" role="alert">{formError}</p>}
    <div className="actions"><Button type="submit" size="sm" disabled={busy || !value.trim()}>{t(busy ? (entry.testable ? 'Testing and saving…' : 'Saving…') : (entry.testable ? 'Test and save' : 'Save'))}</Button><Button type="button" variant="ghost" size="sm" onClick={() => { setEditing(false); setValue(''); setFormError('') }}>{t('Cancel')}</Button></div>
  </form>

  if (!entry.configured) {
    if (!keychain.available) return <p>{t('No system keychain is available; set the key in .env.')}</p>
    return <div className="actions"><Button variant="outline" size="sm" onClick={() => setEditing(true)}>{t('Add key')}</Button></div>
  }

  return <div className="key-panel">
    <p>{t(inDotenv ? 'Stored in .env' : 'Stored in {keychain}', { keychain: keychain.name ?? t('the system keychain') })}</p>
    <div className="actions">
      {entry.testable && <Button variant="outline" size="sm" onClick={test} disabled={testing}>{t(testing ? 'Testing…' : 'Test')}</Button>}
      <Button variant="outline" size="sm" onClick={() => setEditing(true)}>{t('Replace key')}</Button>
      <Button variant="outline" size="sm" className="is-destructive" onClick={() => setConfirmRemove(true)}>{t('Remove')}</Button>
    </div>
    <ConfirmDialog open={confirmRemove} dark={dark} title={t('Remove this key?')} description={t(inDotenv ? 'Its line is deleted from .env. This connection stops working until a new key is added.' : 'This connection stops working until a new key is added.')} confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={remove} onOpenChange={setConfirmRemove} />
  </div>
}

// Warnings are left out: brew prints them for unrelated taps, so they rarely explain a failed install.
function errorLines(output: string): string[] {
  return output.split('\n').map(line => line.trim()).filter(line => /\berror\b|fatal|npm err!|permission denied|could not|not found/i.test(line)).slice(0, 3)
}

function LocalToolDetails({ tool, dark, onChanged }: { tool: LocalTool; dark: boolean; onChanged: () => Promise<void> }) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const toast = useToast()
  const name = tool.name || localToolNames[tool.id] || tool.id
  const running = tool.job?.status === 'running'
  function install() {
    setBusy(true)
    api.installLocalTool(tool.id).then(() => { setConfirmOpen(false); onChanged() }).catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }
  function cancelInstall() {
    setCancelling(true)
    api.cancelLocalToolInstall(tool.id).then(onChanged).catch((e: Error) => toast('error', e.message)).finally(() => setCancelling(false))
  }
  function refresh() {
    setRefreshing(true)
    onChanged().finally(() => setRefreshing(false))
  }
  return <div className="local-tool-details-panel">
    <span className={`status-chip ${tool.installed ? '' : 'is-configured'}`}>{t(tool.installed ? 'Installed' : 'Not installed')}</span>
    {tool.installed && <dl className="local-tool-facts">
      {tool.version && <><dt>{t('Version')}</dt><dd>{tool.version}</dd></>}
      {tool.path && <><dt>{t('Path')}</dt><dd className="local-tool-path">{tool.path.split('/').map((part, i) => <span key={i}>{i > 0 && '/'}{part}<wbr /></span>)}</dd></>}
      {tool.role === 'detected' && <><dt>{t('Role')}</dt><dd>{t('Detected only; it does not run steps')}</dd></>}
      {tool.role === 'imports' && <><dt>{t('Role')}</dt><dd>{t('Imports a collection into a research, read-only')}</dd></>}
    </dl>}
    {tool.kind === 'server' && tool.installed && (tool.running
      ? <>
        <p className="local-tool-note">{t('Running · {endpoint}', { endpoint: tool.endpoint ?? '' })}</p>
        {tool.models && tool.models.length > 0
          ? <ul className="local-tool-models">{tool.models.map(m => <li key={m.id}><span>{m.id}</span><span className="local-tool-model-meta">{m.size_bytes != null && formatBytes(m.size_bytes)}{m.embedding && <span className="status-chip is-configured">{t('Embedding')}</span>}</span></li>)}</ul>
          : <p className="local-tool-note">{t('No models found.')}</p>}
      </>
      : <p className="local-tool-note">{t(tool.id === 'ollama' ? 'Start it with `ollama serve`' : 'Open LM Studio and start its local server')}</p>)}
    {tool.kind === 'app' && tool.installed && <>
      <p className="local-tool-note">{!tool.running ? t('Not running. Open Zotero to import from this computer.') : tool.local_api ? t('Local API on · {endpoint}', { endpoint: tool.endpoint ?? '' }) : t('Running, but its local API is off. Turn on Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”.')}</p>
      <p className="local-tool-note">{t(tool.web_configured ? 'zotero.org: ZOTERO_API_KEY and ZOTERO_LIBRARY_ID are set.' : 'zotero.org: set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in .env to import from the web library.')}</p>
    </>}
    {!tool.installed && (tool.install.available
      ? <>
        <div className="cmd"><code>{tool.install.command.split(' ').map((word, i) => <span key={i}>{i > 0 && ' '}<span>{word}</span></span>)}</code></div>
        <div className="actions"><Button variant="outline" size="sm" onClick={() => setConfirmOpen(true)}>{t('Install')}</Button></div>
        <ConfirmDialog open={confirmOpen} dark={dark} title={t('Install {name}?', { name })} description={t('This runs the command below on this computer.')} context={tool.install.command} confirmLabel={t('Install')} cancelLabel={t('Cancel')} busy={busy} onConfirm={install} onOpenChange={setConfirmOpen} />
      </>
      : <p className="local-tool-note">{tool.install.unavailable_reason}<br /><a href={tool.install.url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>)}
    {tool.job && <>
      {running
        ? <p className="local-tool-note local-tool-progress-head"><LoaderCircle size={14} className="chat-spin" aria-hidden />{t('Installing…')}</p>
        : <p className="local-tool-note">{t(tool.job.status === 'succeeded' ? 'Install finished.' : tool.job.status === 'cancelled' ? 'Installation cancelled.' : 'Install failed.')}</p>}
      {tool.job.status === 'failed' && <>
        {errorLines(tool.job.output).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
        {tool.job.output && <details className="local-tool-details"><summary>{t('Show full output')}</summary><pre className="local-tool-output">{tool.job.output}</pre></details>}
      </>}
      {running && <div className="actions"><Button variant="outline" size="sm" className="is-destructive" onClick={cancelInstall} disabled={cancelling}>{t(cancelling ? 'Cancelling…' : 'Cancel installation')}</Button></div>}
    </>}
    <Button variant="outline" className="connection-recheck" onClick={refresh} disabled={refreshing}><RefreshCw size={14} />{t(refreshing ? 'Refreshing…' : 'Refresh configuration')}</Button>
  </div>
}

const installSteps = ['Creating its Python environment…', 'Installing Marker…', 'Downloading its models (about 3.3 GB)…']

function elapsedText(since: string, now: number) {
  const seconds = Math.max(0, Math.round((now - Date.parse(since)) / 1000))
  const minutes = Math.floor(seconds / 60)
  return minutes ? t('{m} min {s} s', { m: minutes, s: seconds % 60 }) : t('{s} s', { s: seconds })
}

// The library's PDFs by reading state and the PDF Marker is reading now. Marker reports no page progress, so only the
// time since the read started is shown.
export function ReaderProgress({ reader }: { reader: EquationReader }) {
  const [now, setNow] = useState(() => Date.now())
  const reading = reader.reading
  useEffect(() => {
    if (!reading) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [reading])
  const read = reader.pdfs.read ?? 0, none = reader.pdfs.no_math ?? 0, failed = reader.pdfs.failed ?? 0
  const pending = (reader.pdfs.pending ?? 0) + (reader.pdfs.reading ?? 0)
  const total = read + none + failed + pending
  const share = (n: number) => `${total ? (100 * n) / total : 0}%`
  const done = total ? Math.round((100 * (read + none + failed)) / total) : 0
  const legend: [string, number, string][] = [['Read', read, 'is-read'], ['Waiting', pending, 'is-pending'], ['No equations or tables', none, 'is-none'], ['Failed', failed, 'is-failed']]
  return <div className="reader-progress">
    <section className="reader-progress-card" aria-label={t('PDFs in the library')}>
      <div className="reader-progress-head"><span>{t('PDFs in the library')}</span><span>{done}%</span></div>
      <p className="reader-progress-total"><b>{read}</b>{t('/ {total} PDFs read', { total })}</p>
      <div className="reader-progress-bar" role="img" aria-label={t('{read} read · {pending} waiting · {none} without equations or tables · {failed} failed', { read, pending, none, failed })}>
        {read > 0 && <span className="is-read" style={{ width: share(read) }} />}
        {none > 0 && <span className="is-none" style={{ width: share(none) }} />}
        {failed > 0 && <span className="is-failed" style={{ width: share(failed) }} />}
        {reading && <span className="is-reading" style={{ width: share(1) }} />}
      </div>
      <ul className="reader-progress-legend">{legend.map(([label, n, tone]) => <li key={label} className={tone}><i aria-hidden />{t(label)}<b>{n}</b></li>)}</ul>
    </section>
    {reading && <div className="reader-progress-now">
      <LoaderCircle size={16} className="chat-spin" aria-hidden />
      <div>
        <span className="reader-progress-kicker">{t('Reading now')}</span>
        {reading.title && <p className="reader-progress-title">{reading.title}</p>}
        <span className="reader-progress-meta">{t('{n} pages · for {time}', { n: reading.pages, time: elapsedText(reading.started_at, now) })}</span>
      </div>
    </div>}
    {pending > 0 && <p className="local-tool-note">{t('Waiting PDFs are read in the background. An answer or table starts once the PDFs it uses are read.')}</p>}
  </div>
}

function EquationReaderDetails({ reader, dark, onChanged }: { reader: EquationReader; dark: boolean; onChanged: () => Promise<void> }) {
  const [confirm, setConfirm] = useState<'install' | 'remove' | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const job = reader.job
  const running = job?.status === 'running'
  const ready = reader.installed && reader.models_downloaded
  function run(action: () => Promise<unknown>) {
    setBusy(true)
    action().then(() => { setConfirm(null); return onChanged() }).catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }
  return <div className="local-tool-details-panel">
    <span className={`status-chip ${ready ? '' : 'is-configured'}`}>{t(ready ? 'Installed' : 'Not installed')}</span>
    <p className="local-tool-note">{t('Marker reads PDF pages with mathematics from the page image and writes their equations as LaTeX, so answers and table cells read the equations instead of broken PDF text. It runs on this computer; no file leaves it. Answers and cells wait until the equations of the PDFs they read are read.')}</p>
    <p className="local-tool-note">{t('About one Marker equation in fifty was misread in a test on three papers, and a misread equation looks correct. Equations that do not match the PDF’s own text are marked to check against the page.')}</p>
    <dl className="local-tool-facts">
      <dt>{t('Package')}</dt><dd><code className="local-tool-code">{reader.package}</code></dd>
      {reader.size_bytes > 0 && <><dt>{t('Size on disk')}</dt><dd>{formatBytes(reader.size_bytes)}</dd></>}
      {!ready && <><dt>{t('Needs')}</dt><dd>{t('About 4.4 GB of disk · {gb} GB free', { gb: reader.disk_free_gb })}</dd></>}
    </dl>
    {reader.installed && <ReaderProgress reader={reader} />}
    {!ready && !running && (reader.install.available
      ? <div className="actions"><Button variant="outline" size="sm" onClick={() => setConfirm('install')}>{t('Install')}</Button></div>
      : <p className="local-tool-note">{reader.install.unavailable_reason}<br /><a href={reader.install.url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>)}
    {job && <>
      {running
        ? <p className="local-tool-note local-tool-progress-head"><LoaderCircle size={14} className="chat-spin" aria-hidden />{t('Step {step} of {steps}: {what}', { step: job.step, steps: job.steps, what: t(installSteps[job.step - 1] ?? '') })}</p>
        : <p className="local-tool-note">{t(job.status === 'succeeded' ? 'Install finished.' : job.status === 'cancelled' ? 'Installation cancelled.' : 'Install failed.')}</p>}
      {job.status === 'failed' && <>
        {errorLines(job.output).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
      </>}
      {job.output && <details className="local-tool-details"><summary>{t('Show full output')}</summary><pre className="local-tool-output">{job.output}</pre></details>}
      {running && <div className="actions"><Button variant="outline" size="sm" className="is-destructive" onClick={() => run(api.cancelEquationReaderInstall)} disabled={busy}>{t('Cancel installation')}</Button></div>}
    </>}
    {reader.installed && !running && <div className="actions"><Button variant="outline" size="sm" className="is-destructive" onClick={() => setConfirm('remove')} disabled={busy || !!reader.reading} title={reader.reading ? t('It cannot be removed while a PDF is being read') : undefined}>{t('Remove')}</Button></div>}
    <ConfirmDialog open={confirm === 'install'} dark={dark} title={t('Install the equation reader?')} description={t('This downloads Marker and its models, about 4.4 GB, into the DEIXIS data folder. It can take several minutes. Marker’s code is GPL-3.0 and its models have their own license. Afterwards the stored PDFs are read in the background; that can take hours for a large library.')} context={reader.path} confirmLabel={t('Install')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.installEquationReader)} onOpenChange={open => setConfirm(open ? 'install' : null)} />
    <ConfirmDialog open={confirm === 'remove'} dark={dark} title={t('Remove the equation reader?')} description={t('Marker and its models are deleted. Equations already read stay in the stored text; new PDFs are no longer read.')} confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.removeEquationReader)} onOpenChange={open => setConfirm(open ? 'remove' : null)} />
  </div>
}

// The local OCR tool (D51): detected, not installed by DEIXIS; the command to install it is shown when it or a language is missing.
function OcrToolDetails({ tool, onRefresh }: { tool: OcrTool; onRefresh: () => Promise<void> }) {
  const [refreshing, setRefreshing] = useState(false)
  const refresh = () => { setRefreshing(true); void onRefresh().finally(() => setRefreshing(false)) }
  return <div className="local-tool-details-panel">
    <span className={`status-chip ${tool.available && !tool.missing_languages.length ? '' : 'is-configured'}`}>{t(!tool.available ? 'Not installed' : tool.missing_languages.length ? 'Installed · languages missing' : 'Installed')}</span>
    <p className="local-tool-note">{t('Tesseract reads PDF pages that have no text layer, such as scanned articles, when you choose Read with OCR on a source. It runs on this computer; no file leaves it, and the PDF is not changed.')}</p>
    <p className="local-tool-note">{t('OCR text is labelled wherever it is quoted. On four scanned articles about 0.2–1.5% of characters were misread and equations were unusable; numbers and equations from OCR text are not checked against the page.')}</p>
    <dl className="local-tool-facts">
      <dt>{t('Version')}</dt><dd>{tool.version ?? t('not found')}</dd>
      {tool.available && <><dt>{t('Languages')}</dt><dd>{ocrLanguagesText(tool.languages)}</dd></>}
      {tool.missing_languages.length > 0 && <><dt>{t('Missing')}</dt><dd>{ocrLanguagesText(tool.missing_languages)}</dd></>}
    </dl>
    {tool.reason && <p className="local-tool-note">{tool.reason}</p>}
    <Button variant="outline" className="connection-recheck" onClick={refresh} disabled={refreshing}><RefreshCw size={14} />{t(refreshing ? 'Checking…' : 'Check again')}</Button>
  </div>
}

function ModelCatalogue({ model }: { model: ModelHealth }) {
  const models = model.models ?? []
  return <>
    <h3 className="source-section">{t('Models listed · {n}', { n: models.length })}</h3>
    {models.length > 0 && <ul className="connection-models">{models.map(item => <li key={item.id}>
      <span className="connection-model-copy"><strong>{item.display_name}</strong>{item.description && <small>{item.description}</small>}{item.resolved_model && item.resolved_model !== item.id && <code>{item.resolved_model}</code>}</span>
      <span className="connection-model-meta">
        {item.is_default && <small>{t('default')}</small>}
        {(item.reasoning_efforts ?? []).length > 0
          ? <span className="reasoning-levels" aria-label={t('Thinking levels')}>{item.reasoning_efforts?.map(level => <span key={level.id} title={level.description || undefined}>{reasoningLabel(level.id)}</span>)}</span>
          : <small>{t('No thinking levels')}</small>}
      </span>
    </li>)}</ul>}
  </>
}

// The built-in embedding model (slice 21): disk sizes before the download, the job's steps while it runs, then ready
// with the time of the last full file check. Downloaded, checked and ready are told apart; sizes are disk sizes.
const builtinSteps: Record<string, string> = {
  environment: 'Creating its Python environment…', package: 'Installing fastembed…',
  model_files: 'Downloading the model files…', start_check: 'Checking that the model starts and answers…',
}
const aboutMb = (bytes: number) => Math.round(bytes / 1e6)

function BuiltinEmbeddingPanel({ builtin, dark, onChanged }: { builtin: BuiltinEmbedding; dark: boolean; onChanged: () => Promise<void> }) {
  const [confirm, setConfirm] = useState<'install' | 'remove' | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  function run(action: () => Promise<unknown>) {
    setBusy(true)
    action().then(() => { setConfirm(null); return onChanged() }).catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }
  if (builtin.status === 'unsupported_platform') return <p className="local-tool-note">{t('The built-in model is not available on Windows yet')}</p>
  const { sizes, job } = builtin
  const running = builtin.status === 'installing'
  const failed = !running && job?.status === 'failed' && builtin.status !== 'ready'
  const sizeVars = { total: aboutMb(sizes.runtime_bytes + sizes.model_bytes), runtime: aboutMb(sizes.runtime_bytes), model: aboutMb(sizes.model_bytes), python: aboutMb(sizes.python_bytes) }
  const checked = builtin.last_full_check ? new Date(builtin.last_full_check.at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) : null
  const canDownload = !running && builtin.status !== 'ready' && builtin.status !== 'installing_elsewhere' && builtin.status !== 'removing'
  const stepName = job ? t(builtinSteps[job.step_name ?? ''] ?? '') : ''
  return <div className="semantic-builtin">
    {builtin.status === 'ready' && <span className="status-chip">{checked ? t('Ready · files checked {time}', { time: checked }) : t('Ready')}</span>}
    {builtin.status === 'ready' && <p className="local-tool-note">{t('Files checked at install and each time the model starts.')}</p>}
    {builtin.status === 'files_do_not_match' && <p className="local-tool-error">{t('The model files do not match the checked copy, so the model is not used. Download them again.')}</p>}
    {builtin.status === 'installing_elsewhere' && <p className="local-tool-note">{t('Being downloaded by another DEIXIS process.')}</p>}
    {builtin.status === 'removing' && <p className="local-tool-note">{t('Being removed…')}</p>}
    {builtin.status === 'remove_failed' && <>
      <p className="local-tool-error">{t('Removal did not finish: some files could not be deleted.')}</p>
      {(job?.output ?? '').split('\n').filter(Boolean).slice(0, 4).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
    </>}
    {canDownload && <p className="local-tool-note">{t('Needs about {total} MB of disk (runtime about {runtime} MB installed, model {model} MB), plus about {python} MB if uv has to download Python 3.12, plus uv’s download cache (not measured).', sizeVars)}</p>}
    {running && job && <p className="local-tool-note local-tool-progress-head" role="status"><LoaderCircle size={14} className="chat-spin" aria-hidden />
      {t('Step {step} of {steps}: {what}', { step: job.step, steps: job.steps, what: stepName })}
      {job.step_name === 'model_files' && job.bytes_total ? ` ${t('{done} of {total} MB', { done: aboutMb(job.bytes_done ?? 0), total: aboutMb(job.bytes_total) })}` : ''}</p>}
    {failed && job && <>
      <p className="local-tool-error">{t('Download failed at step {step} of {steps}: {what}', { step: job.step, steps: job.steps, what: stepName })}</p>
      {errorLines(job.output).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
    </>}
    {!running && job?.status === 'cancelled' && builtin.status !== 'ready' && <p className="local-tool-note">{t('Download cancelled.')}</p>}
    {job?.output && (failed || running) && <details className="local-tool-details"><summary>{t('Show full output')}</summary><pre className="local-tool-output">{job.output}</pre></details>}
    {canDownload && (builtin.uv.available
      ? <div className="actions"><Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirm('install')}>{t(failed || builtin.status === 'files_do_not_match' ? 'Try again' : 'Download')}</Button></div>
      : <p className="local-tool-note">{builtin.uv.reason}<br /><a href={builtin.uv.url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>)}
    {running && <div className="actions"><Button variant="outline" size="sm" className="is-destructive" disabled={busy} onClick={() => run(api.cancelBuiltinEmbedding)}>{t('Cancel download')}</Button></div>}
    {(builtin.status === 'ready' || builtin.status === 'remove_failed') && <div className="actions"><Button variant="outline" size="sm" className="is-destructive" disabled={busy} onClick={() => setConfirm('remove')}>{t('Remove')}</Button></div>}
    <ConfirmDialog open={confirm === 'install'} dark={dark} neutral title={t('Download the built-in model?')}
      description={t('It takes about {total} MB of disk in the DEIXIS data folder: the runtime (about {runtime} MB installed) and the model files ({model} MB), plus about {python} MB if uv has to download Python 3.12, and uv’s download cache (not measured). The model is downloaded once, from Hugging Face. For semantic search, no text leaves the computer.', sizeVars)}
      context={builtin.path} confirmLabel={t('Download')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.installBuiltinEmbedding)} onOpenChange={open => setConfirm(open ? 'install' : null)} />
    <ConfirmDialog open={confirm === 'remove'} dark={dark} title={t('Remove the built-in model?')}
      description={t('Its environment and model files are deleted. Similarities it already stored stay and may still be used for the same question revision; records not yet scored are ranked without it until you download it again.')}
      confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.removeBuiltinEmbedding)} onOpenChange={open => setConfirm(open ? 'remove' : null)} />
  </div>
}

function GeminiKeyPath() {
  const [before, after] = t('Get a free key: sign in at {link}, create a key, paste it under Cloud models → Gemini.').split('{link}')
  return <p className="local-tool-note">{before}<a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer">aistudio.google.com/apikey</a>{after}</p>
}

export function ConnectionsTab({ dark }: { dark: boolean }) {
  const [data, setData] = useState<Connections | null>(null)
  const [busy, setBusy] = useState(false)
  const [refreshingModel, setRefreshingModel] = useState<string | null>(null)
  const [error, setError] = useState('')
  // The selection outlives `open` so the drawer keeps its content while it animates closed.
  const [selected, setSelected] = useState<Selected | null>(null)
  const [open, setOpen] = useState(false)
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [tools, setTools] = useState<LocalTools | null>(null)
  const [toolsError, setToolsError] = useState('')
  const [reader, setReader] = useState<EquationReader | null>(null)
  const [ocrTool, setOcrTool] = useState<OcrTool | null>(null)
  const [semantic, setSemantic] = useState<SemanticSearch | null>(null)
  const [semError, setSemError] = useState('')
  const [semProvider, setSemProvider] = useState<SemanticSearchProvider | null>(null)
  const [semModel, setSemModel] = useState<string | null>(null)
  const [semBusy, setSemBusy] = useState(false)
  const [builtin, setBuiltin] = useState<BuiltinEmbedding | null>(null)
  const toast = useToast()

  const load = useCallback((refresh: boolean) => {
    setBusy(true)
    api.connections(refresh).then(result => { setData(result); setError('') }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }, [])
  const loadCredentials = useCallback(() => { api.credentials().then(setCredentials).catch(() => { /* shown inline per key panel */ }) }, [])
  const loadTools = useCallback((refresh: boolean) => api.localTools(refresh).then(result => { setTools(result); setToolsError('') }).catch((e: Error) => { setToolsError(e.message) }), [])
  const loadReader = useCallback(() => api.equationReader().then(setReader).catch((e: Error) => { setToolsError(e.message) }), [])
  const loadOcr = useCallback(() => api.ocr().then(setOcrTool).catch((e: Error) => { setToolsError(e.message) }), [])
  const loadSemantic = useCallback(() => { api.semanticSearch().then(result => { setSemantic(result); setSemError('') }).catch((e: Error) => setSemError(e.message)) }, [])
  const loadBuiltin = useCallback(() => api.builtinEmbedding().then(setBuiltin).catch((e: Error) => setSemError(e.message)), [])
  useEffect(() => { load(false) }, [load])
  useEffect(() => { loadCredentials() }, [loadCredentials])
  useEffect(() => { loadTools(false) }, [loadTools])
  useEffect(() => { loadSemantic() }, [loadSemantic])
  useEffect(() => { void loadBuiltin() }, [loadBuiltin])
  useEffect(() => {
    if (builtin?.status !== 'installing' && builtin?.status !== 'installing_elsewhere' && builtin?.status !== 'removing') return
    const timer = window.setInterval(() => { void loadBuiltin().then(() => loadSemantic()) }, 1500)
    return () => window.clearInterval(timer)
  }, [builtin, loadBuiltin, loadSemantic])
  useEffect(() => { void loadReader() }, [loadReader])
  useEffect(() => { void loadOcr() }, [loadOcr])
  useEffect(() => {
    if (reader?.job?.status !== 'running' && !reader?.reading) return
    const timer = window.setInterval(() => { void loadReader() }, reader?.job?.status === 'running' ? 2000 : 10000)
    return () => window.clearInterval(timer)
  }, [reader, loadReader])
  useEffect(() => { if (semantic) { setSemProvider(semantic.provider); setSemModel(semantic.model) } }, [semantic])
  useEffect(() => {
    if (!tools?.tools.some(tool => tool.job?.status === 'running')) return
    const timer = window.setInterval(() => loadTools(false), 2000)
    return () => window.clearInterval(timer)
  }, [tools, loadTools])

  const reloadAfterKeyChange = useCallback(() => { loadCredentials(); load(true); loadSemantic() }, [loadCredentials, load, loadSemantic])

  const refreshModel = useCallback((id: string, notify = false) => {
    setRefreshingModel(id)
    return api.modelConnection(id, true).then(result => {
      setData(current => current ? { ...current, models: { ...current.models, [id]: result } } : current)
      setError('')
      if (notify) {
        const label = modelNames[id] ?? id
        if (result.ready) toast('success', t('{name}: ready', { name: label }))
        else toast('warning', `${label}: ${result.reason ?? t('not ready')}`)
      }
    }).catch((e: Error) => {
      if (notify) toast('error', t('Check failed: {message}', { message: e.message }))
      else toast('error', t('Could not refresh model catalogue: {message}', { message: e.message }))
    }).finally(() => setRefreshingModel(current => current === id ? null : current))
  }, [toast])
  const show = (item: Selected) => {
    setSelected(item)
    setOpen(true)
    if (item.kind === 'model') void refreshModel(item.id)
  }
  const recheck = () => {
    if (!selected) return
    if (selected.kind === 'model') { void refreshModel(selected.id, true); return }
    setBusy(true)
    api.connections(true).then(result => {
      setData(result); setError('')
      // This refreshes configuration only; it does not spend a provider request or verify access.
      const p = result.providers.find(x => x.id === selected.id)
      if (p && hasProviderAccessMode(p.access_mode)) toast('success', t('Configuration refreshed; live access was not tested.'))
      else toast('warning', t('{name}: key not configured', { name }))
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
        : selected.kind === 'api-key' ? t('OpenAI API') : selected.kind === 'equation-reader' ? t('Equation reader (Marker)') : selected.kind === 'ocr-tool' ? t('OCR (Tesseract)') : localTool?.name || localToolNames[selected.id] || selected.id
    : ''
  const modelEntries = Object.entries(data?.models ?? {})
  const availableModels = modelEntries.filter(([, model]) => !isPlannedModel(model.reason))
  const plannedModels = modelEntries.filter(([, model]) => isPlannedModel(model.reason))
  const signInModels = availableModels.filter(([, m]) => m.key_configured === undefined)
  const keyModels = availableModels.filter(([, m]) => m.key_configured !== undefined)
  const modelCard = ([id, m]: (typeof modelEntries)[number]) => <ConnectionTile key={id} icon={<ConnectionIcon id={id} />} name={modelNames[id] ?? id} ok={m.ready} status={m.ready ? t('Ready') : m.signed_in === false && m.installed ? t('Not signed in') : m.installed === false ? t('Not installed') : t('Not connected')} active={isActive('model', id)} onClick={() => show({ kind: 'model', id })} />
  const toolCard = (tool: LocalTool) => <ConnectionTile key={tool.id} icon={<ConnectionIcon id={localToolIcon(tool.id)} />} name={tool.name || localToolNames[tool.id] || tool.id} ok={tool.installed} status={t(tool.job?.status === 'running' ? 'Installing…' : tool.installed ? 'Installed' : 'Not installed')} active={isActive('local-tool', tool.id)} onClick={() => show({ kind: 'local-tool', id: tool.id })} />
  const providerCard = (p: Connections['providers'][number]) => <ConnectionTile key={p.id} icon={<ConnectionIcon id={p.id} />} name={providerNames[p.id] ?? p.id} ok={p.access_mode === 'api_key'} status={p.role === 'verification' ? `${providerRole(p.role)} · ${providerStatus(p.access_mode)}` : providerStatus(p.access_mode)} active={isActive('provider', p.id)} onClick={() => show({ kind: 'provider', id: p.id })} />
  const keylessProviders = (data?.providers ?? []).filter(p => !providerKeyEnv[p.id])
  const keyProviders = (data?.providers ?? []).filter(p => providerKeyEnv[p.id])

  const openaiKey = credentials?.keys.find(k => k.env === 'OPENAI_API_KEY')
  const geminiKey = credentials?.keys.find(k => k.env === 'GEMINI_API_KEY')
  const deepseekKey = credentials?.keys.find(k => k.env === 'DEEPSEEK_API_KEY')

  const cliTools = (tools?.tools ?? []).filter(tool => tool.kind === 'cli')
  const serverTools = (tools?.tools ?? []).filter(tool => tool.kind === 'server')
  const appTools = (tools?.tools ?? []).filter(tool => tool.kind === 'app')
  const machine = tools?.machine
  const hasMachineInfo = machine && (machine.chip || machine.memory_gb != null || machine.disk_free_gb != null)

  const semanticLabels: Record<SemanticSearchProvider, string> = { gemini: 'Gemini', builtin: t('This computer · built-in'), openai: 'OpenAI', ollama: t('This computer · Ollama'), lm_studio: t('This computer · LM Studio'), off: t('Off · keyword search only') }
  // What a choice says under its row (slice 21): Gemini's key path and languages, the built-in model's place and state.
  const optionBody = (opt: SemanticSearchOption) => {
    if (opt.provider === 'gemini') return <>
      <p className="local-tool-note">{t('Reads the question in any language. Needs a Google AI Studio key; a free key works.')}</p>
      {!opt.available && <GeminiKeyPath />}
    </>
    if (opt.provider === 'builtin') return <>
      <p className="local-tool-note">{t('Runs on this computer. No key, no account. For semantic search, no text leaves the computer; the model you chose for the research steps still receives what it receives today. English only: a research whose question is not in English needs one English sentence.')}</p>
      <p className="local-tool-note">{t('Measured on one Apple M1 Pro: 1,369 records took 51 seconds, 6,696 records about 4 minutes. Other computers were not measured.')}</p>
      {builtin && <BuiltinEmbeddingPanel builtin={builtin} dark={dark} onChanged={async () => { await loadBuiltin(); loadSemantic() }} />}
    </>
    return null
  }

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
    {error && <Notice tone="error">{error}</Notice>}

    <section className="connections-group">
      <h2 className="with-icon"><Cloud size={20} aria-hidden />{t('Cloud models')}</h2>
      <p className="legacy-mini-note">{t('Passages are sent to the provider you choose. Once a key is saved it is never shown again; it can only be replaced or removed.')}</p>
      <h3 className="connections-subhead">{t('Account sign-in')}</h3>
      <div className="connection-grid">{signInModels.map(modelCard)}</div>
      <h3 className="connections-subhead">{t('API key')}</h3>
      <div className="connection-grid">
        {keyModels.map(modelCard)}
        <ConnectionTile icon={<ConnectionIcon id="openai" />} name={t('OpenAI API')} ok={!!openaiKey?.configured} status={t(openaiKey?.configured ? 'Key configured' : 'Not connected')} active={isActive('api-key', 'OPENAI_API_KEY')} onClick={() => show({ kind: 'api-key', id: 'OPENAI_API_KEY' })} />
      </div>
      {plannedModels.length > 0 && <details className="planned-connections"><summary>{t('Planned model connections · {n}', { n: plannedModels.length })}</summary><div className="connection-grid">{plannedModels.map(modelCard)}</div></details>}
    </section>

    <section className="connections-group">
      <h2 className="with-icon"><Laptop size={20} aria-hidden />{t('On this computer')}</h2>
      <p className="legacy-mini-note">{t('Found from this computer’s PATH, installed apps and local server ports. Install runs the command shown, after you confirm.')}</p>
      {hasMachineInfo && <p className="local-tool-machine">
        {machine?.chip && <span>{t('This computer: {chip}', { chip: machine.chip })}</span>}
        {machine?.memory_gb != null && <span>{t('Memory: {gb} GB', { gb: machine.memory_gb })}</span>}
        {machine?.disk_free_gb != null && <span>{t('Free disk: {gb} GB', { gb: machine.disk_free_gb })}</span>}
      </p>}
      {toolsError && <Notice tone="error">{toolsError}</Notice>}
      <h3 className="connections-subhead with-icon"><SquareTerminal size={15} aria-hidden />{t('Command-line tools')}</h3>
      <div className="connection-grid">{cliTools.map(toolCard)}</div>
      <h3 className="connections-subhead with-icon"><Server size={15} aria-hidden />{t('Local model servers')}</h3>
      <div className="connection-grid">{serverTools.map(toolCard)}</div>
      <p className="legacy-mini-note">{t('Local models do not run research steps in this version; embedding models can be chosen for semantic search.')}</p>
      {reader && <>
        <h3 className="connections-subhead with-icon"><Sigma size={15} aria-hidden />{t('Equation reader')}</h3>
        <div className="connection-grid"><ConnectionTile icon={<Sigma size={18} aria-hidden />} name="Marker" ok={reader.installed && reader.models_downloaded} status={reader.job?.status === 'running' ? t('Installing…') : t(reader.installed && reader.models_downloaded ? 'Installed' : 'Not installed')} active={isActive('equation-reader', 'marker')} onClick={() => show({ kind: 'equation-reader', id: 'marker' })} /></div>
      </>}
      {ocrTool && <>
        <h3 className="connections-subhead with-icon"><ScanText size={15} aria-hidden />{t('OCR for scanned PDFs')}</h3>
        <div className="connection-grid"><ConnectionTile icon={<ScanText size={18} aria-hidden />} name="Tesseract" ok={ocrTool.available} status={t(!ocrTool.available ? 'Not installed' : !ocrTool.missing_languages.length ? 'Installed' : ocrTool.languages.join() === 'eng' ? 'English only' : 'Languages missing')} active={isActive('ocr-tool', 'tesseract')} onClick={() => show({ kind: 'ocr-tool', id: 'tesseract' })} /></div>
      </>}
      {appTools.length > 0 && <>
        <h3 className="connections-subhead with-icon"><BookMarked size={15} aria-hidden />{t('Reference managers')}</h3>
        <div className="connection-grid">{appTools.map(toolCard)}</div>
        <p className="legacy-mini-note">{t('Collections are imported read-only from a research’s Sources tab or the home composer’s Add sources menu.')}</p>
      </>}
    </section>

    <section className="connections-group">
      <h2 className="with-icon"><Sparkles size={20} aria-hidden />{t('Semantic search')}</h2>
      <p className="legacy-mini-note">{t('The question and passages are matched by meaning even when the words differ, and the result is fused with keyword search. Changing the provider embeds passages again; earlier vectors are kept. Similarity only ranks passages; it does not show that a passage supports a claim.')}</p>
      {semError && <Notice tone="error">{semError}</Notice>}
      {semantic && <>
        <div className="semantic-choices" role="radiogroup" aria-label={t('Semantic search provider')}>
          {semantic.options.map(opt => {
            const checked = semProvider === opt.provider
            const body = optionBody(opt)
            return <div className="semantic-option" key={opt.provider}>
              <label className={`semantic-choice ${!opt.available ? 'is-disabled' : ''}`}>
                <input type="radio" name="semantic-provider" checked={checked} disabled={!opt.available} onChange={() => chooseSemantic(opt.provider, opt.models)} />
                {opt.provider === 'off' ? <TextSearch className="semantic-off-icon" size={16} aria-hidden /> : <ConnectionIcon id={opt.provider} />}
                <strong>{semanticLabels[opt.provider]}</strong>
                {!needsModel(opt.provider) && opt.models[0] && <code className="semantic-model-name">{opt.models[0]}</code>}
                {opt.available ? <span className="status-chip">{t('Available')}</span> : <span className="semantic-reason">{t(opt.reason ?? '')}</span>}
                {needsModel(opt.provider) && checked && <select className="semantic-model" value={semModel ?? ''} onChange={e => setSemModel(e.target.value)}>{opt.models.map(m => <option key={m} value={m}>{m}</option>)}</select>}
              </label>
              {body && <div className="semantic-option-body">{body}</div>}
            </div>
          })}
        </div>
        {semProvider && <p className="legacy-mini-note">{semProvider === 'off' ? t('Sources get no similarity score; passages are ranked by keyword match only. No text is sent anywhere.')
          : semProvider === 'gemini' ? t('Passage text is sent to Google. If your key is on Google’s free tier, Google may use the text you send to improve its products. DEIXIS cannot tell which tier your key is on.')
          : semProvider === 'openai' ? t('Passage text is sent to {service}.', { service: 'OpenAI' })
          : semProvider === 'builtin' ? t('For semantic search, no text leaves the computer.') : t('Passage text stays on this computer.')}</p>}
        <div className="actions"><Button size="sm" disabled={semBusy || !semProvider || (needsModel(semProvider) && !semModel)} onClick={saveSemantic}>{t(semBusy ? 'Saving…' : 'Save')}</Button></div>
      </>}
    </section>

    <section className="connections-group">
      <h2 className="with-icon"><GraduationCap size={20} aria-hidden />{t('Scholarly sources')}</h2>
      <h3 className="connections-subhead">{t('No API key')}</h3>
      <div className="connection-grid">{keylessProviders.map(providerCard)}</div>
      <h3 className="connections-subhead">{t('API key')}</h3>
      <div className="connection-grid">{keyProviders.map(providerCard)}</div>
      <p className="legacy-mini-note">{t('Every provider with the access it needs is enabled for new researches, and the model chooses which to query. Access and remaining quota are recorded with each request rather than guaranteed in advance.')}</p>
    </section>

    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet source-sheet connection-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader><SheetTitle>{t(selected?.kind === 'provider' ? 'Scholarly source' : selected?.kind === 'api-key' ? 'Model connection' : selected?.kind === 'local-tool' || selected?.kind === 'equation-reader' || selected?.kind === 'ocr-tool' ? 'Local tool details' : 'Model connection')}</SheetTitle><SheetDescription className="sr-only">{t('{name} details', { name })}</SheetDescription></SheetHeader>
        <div className="sheet-body">
          {selected && <div className="connection-sheet-head">{selected.kind === 'equation-reader' ? <Sigma size={20} aria-hidden /> : selected.kind === 'ocr-tool' ? <ScanText size={20} aria-hidden /> : <ConnectionIcon id={selected.kind === 'local-tool' ? localToolIcon(selected.id) : selected.id} />}<h2 className="source-title">{name}</h2></div>}
          {selected?.kind === 'equation-reader' && reader && <EquationReaderDetails reader={reader} dark={dark} onChanged={loadReader} />}
          {selected?.kind === 'ocr-tool' && ocrTool && <OcrToolDetails tool={ocrTool} onRefresh={loadOcr} />}
          {localTool && <LocalToolDetails key={localTool.id} tool={localTool} dark={dark} onChanged={() => loadTools(true)} />}
          {model && <>
            {refreshingModel === selected?.id && <p className="source-byline connection-catalog-refresh"><LoaderCircle size={14} className="chat-spin" aria-hidden />{t('Refreshing model catalogue…')}</p>}
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
            </>}
            {selected?.id === 'claude' && <>
              <p className="source-byline">{t('DEIXIS runs Claude Code through the official Agent SDK with tools, MCP servers, skills and instruction files disabled, and starts a new non-persistent session for every step.')}</p>
              <div className="connection-checks">
                {check('CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
                {check(t('Signed in to Claude Code'), model.signed_in ? t('yes · {plan}', { plan: model.plan_type ?? model.account_type ?? '' }) : t('no'))}
                {check(t('Instruction files loaded'), model.isolation ? String(model.isolation.instruction_sources) : t('not checked'))}
                {check(t('MCP servers with tools'), model.isolation ? (model.isolation.live_mcp_servers.join(', ') || t('none')) : t('not checked'))}
              </div>
            </>}
            {selected?.id === 'gemini' && <>
              <p className="source-byline">{t('DEIXIS calls the Gemini API directly with GEMINI_API_KEY, with no tools, instruction files or CLI agent prompt, and one new request per step. The Gemini CLI is only detected; it does not run steps.')}</p>
              <div className="connection-checks">
                {check(t('API key (GEMINI_API_KEY)'), model.key_configured ? t('set') : t('not set'))}
                {check('Gemini CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
                {check(t('Semantic passage search'), model.key_configured ? t('on · passage text is sent to Google') : t('off'))}
              </div>
              {credentials && <KeyPanel env="GEMINI_API_KEY" entry={geminiKey} keychain={credentials.keychain} dark={dark} onSaved={reloadAfterKeyChange} />}
            </>}
            {selected?.id === 'deepseek' && <>
              <p className="source-byline">{t('DEIXIS calls the DeepSeek API directly with DEEPSEEK_API_KEY, with no tools or instruction files and one new request per step.')}</p>
              <div className="connection-checks">
                {check(t('API key (DEEPSEEK_API_KEY)'), model.key_configured ? t('set') : t('not set'))}
              </div>
              {credentials && <KeyPanel env="DEEPSEEK_API_KEY" entry={deepseekKey} keychain={credentials.keychain} dark={dark} onSaved={reloadAfterKeyChange} />}
            </>}
            <ModelCatalogue model={model} />
          </>}
          {selected?.kind === 'api-key' && <>
            <span className={`status-chip ${openaiKey?.configured ? '' : 'is-configured'}`}>{t(openaiKey?.configured ? 'Key configured' : 'Not connected')}</span>
            <p className="source-byline">{t('Passages are sent to the provider you choose. Once a key is saved it is never shown again; it can only be replaced or removed.')}</p>
            {credentials && <KeyPanel env="OPENAI_API_KEY" entry={openaiKey} keychain={credentials.keychain} dark={dark} onSaved={reloadAfterKeyChange} />}
          </>}
          {provider && <>
            {hasProviderAccessMode(provider.access_mode) && <span className={`status-chip ${provider.access_mode === 'keyless' ? 'is-configured' : ''}`}>{providerStatus(provider.access_mode)}</span>}
            <p className="source-byline">{provider.note}</p>
            <div className="connection-checks">{check(t('Used for'), providerRole(provider.role))}{check(t('Access mode'), provider.access_mode ? t(provider.access_mode) : t('none'))}</div>
            {credentials && providerKeyEnv[provider.id] && <KeyPanel env={providerKeyEnv[provider.id]} entry={credentials.keys.find(k => k.env === providerKeyEnv[provider.id])} keychain={credentials.keychain} dark={dark} onSaved={reloadAfterKeyChange} />}
          </>}
          {!localTool && selected?.kind !== 'equation-reader' && selected?.kind !== 'ocr-tool' && selected?.kind !== 'api-key' && <Button variant="outline" className="connection-recheck" onClick={recheck} disabled={busy || refreshingModel === selected?.id}><RefreshCw size={14} />{t(provider ? (busy ? 'Refreshing…' : 'Refresh configuration') : (refreshingModel === selected?.id ? 'Checking…' : 'Check again'))}</Button>}
        </div>
      </SheetContent>
    </Sheet>
  </div>
}
