import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Ban, ChevronRight, Copy, Cpu, FileText, HardDrive, MemoryStick, Link, LoaderCircle, RefreshCw, RotateCw, ScanText, Server, Sigma, TriangleAlert, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ConfirmDialog } from './ConfirmDialog'
import { DataLocationCard } from './DataLocation'
import { api, ApiError, libraryImportsApi, type AccountSignIn, type BuiltinEmbedding, type Connections, type Credentials, type KeyEntry, type Keychain, type EquationReader, type LocalTool, type OcrTool, type LocalTools, type ProviderTest, type ModelHealth, type ReferenceImport, type SemanticSearch, type SemanticSearchOption, type SemanticSearchProvider } from './api'
import { useToast } from './Toast'
import { ocrLanguagesText } from './ocr'
import { t, uiLocale } from './i18n'
import { serviceErrorSentence, healthReasonText, compatConnectionKeys, connectionNames as modelNames, localToolIcon, localToolNames, providerRole, reasoningLabel } from './labels'
import { ConnectionIcon } from './connectionIcons'
import { writeClipboard } from './clipboard'
import { Notice } from './Notice'

const providerNames: Record<string, string> = {
  semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', biorxiv: 'bioRxiv', pubmed: 'PubMed', openalex: 'OpenAlex', scopus: 'Scopus', ieee_xplore: 'IEEE Xplore', core: 'CORE', serpapi: 'SerpApi',
}
// Providers that take their own key; env names come from the credentials contract.
const providerKeyEnv: Record<string, string> = { openalex: 'OPENALEX_API_KEY', biorxiv: 'OPENALEX_API_KEY', semantic_scholar: 'S2_API_KEY', pubmed: 'NCBI_API_KEY', ieee_xplore: 'IEEE_API_KEY', scopus: 'SCOPUS_API_KEY', core: 'CORE_API_KEY', serpapi: 'SERPAPI_API_KEY' }
// The mockup's order comes first (plan ST7); every other registered connector follows in the registry's order.
const PROVIDER_ORDER = ['openalex', 'semantic_scholar', 'crossref', 'scopus', 'arxiv']
// What the fast path asks each source for (CLAUDE.md, D12); the others carry their role in the registry.
const providerUse: Record<string, string> = {
  openalex: 'Search and citation chain', semantic_scholar: 'Abstracts and bulk search', crossref: 'Abstracts and metadata checks',
  scopus: 'Abstracts, once its full view is confirmed',
}
// What happens while a provider has no key (the keyless modes in providers/*.py, required keys in registry.py).
const providerNoKey: Record<string, string> = {
  openalex: 'Without a key, DEIXIS uses the daily budget OpenAlex gives to requests without a key. When it runs out, requests wait until it resets, and a run can pause.',
  biorxiv: 'bioRxiv is searched through OpenAlex, so without the OpenAlex key it shares the same keyless daily budget.',
  semantic_scholar: 'Without a key, Semantic Scholar often turns requests away at busy times. DEIXIS retries, so abstracts and bulk search results come in more slowly and some may be missing.',
  pubmed: 'Without a key, PubMed allows 3 requests per second instead of 10, so searches can be slower.',
  ieee_xplore: 'Without a key, IEEE Xplore is not searched.',
  scopus: 'Without a key, Scopus is not used: no Scopus abstracts are read.',
  core: 'Without a key, CORE is not searched.',
  serpapi: 'Without a key, SerpApi is not searched.',
}
// Sources whose requests carry the contact email as `mailto` (openalex.py, crossref.py).
const MAILTO_PROVIDERS = new Set(['openalex', 'crossref'])
// The model connections that sign in with an account on this computer, and the command-line tool each one runs.
const ACCOUNT_TOOLS: Record<string, { tool: LocalTool['id']; name: string }> = { codex: { tool: 'codex', name: 'Codex CLI' }, claude: { tool: 'claude_code', name: 'Claude Code' } }
const SERVER_IDS = ['ollama', 'lm_studio']
const formatBytes = (bytes: number) => bytes / 1e9 >= 1 ? t('{gb} GB', { gb: (bytes / 1e9).toFixed(1) }) : t('{mb} MB', { mb: Math.round(bytes / 1e6) })
const clock = (iso: string | number) => new Date(iso).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })

// Settings icons, drawn in black and white (Settings.css): brand marks where connectionIcons.tsx has one, a plain glyph otherwise.
const glyph = (icon: ReactNode) => <span className="connection-icon" aria-hidden="true">{icon}</span>
const GLYPHS: Record<string, ReactNode> = {
  ocr: glyph(<ScanText strokeWidth={1.8} />), marker: glyph(<Sigma strokeWidth={1.8} />), servers: glyph(<Server strokeWidth={1.8} />),
  server: glyph(<Server strokeWidth={1.8} />), 'reference-files': glyph(<FileText strokeWidth={1.8} />), off: glyph(<Ban strokeWidth={1.8} />),
}
const settingsIcon = (key: string) => GLYPHS[key] ?? <ConnectionIcon id={localToolIcon(key)} />

type Selected = { kind: 'account' | 'model' | 'cli' | 'servers' | 'equation-reader' | 'ocr-tool' | 'provider' | 'api-key' | 'zotero' | 'reference-files'; id: string }
type Tone = 'ok' | 'no' | 'warn'

// Why a service refused a new key, in plain words, with the HTTP code it answered. The readings follow each
// provider's published error codes (Oct 2026); a provider that documents nothing gets the generic reading.
function keyRefusal(service: string, env: string, status: unknown): string | null {
  const v = { service, code: String(status) }
  if (status === 401) return t('{service} does not recognise this key (HTTP 401). It may be mistyped, cut short or deleted. Copy it again or create a new key.', v)
    + (env === 'DASHSCOPE_API_KEY' || env === 'MOONSHOT_API_KEY' ? ' ' + t('A key made on the China platform does not work on the international one, and the other way round.') : '')
  if (status === 402) return t('{service} accepts this key, but the account has no balance left (HTTP 402). Add credit on the provider’s site and try again.', v)
  if (status === 403) return env === 'OPENAI_API_KEY' ? t('{service} does not allow this key here (HTTP 403). The service may not be offered in your country, or the key may be restricted. Check the key’s permissions.', v)
    : env === 'MISTRAL_API_KEY' ? t('{service} knows this key, but your plan does not include the model used for the test (HTTP 403).', v)
    : env === 'DASHSCOPE_API_KEY' ? t('{service} knows this key, but the account has no access to the model, or its free quota is used up (HTTP 403).', v)
    : t('{service} knows this key but does not let it make the test request (HTTP 403). The key may be restricted, or the account may lack access or credit. Check the key on the provider’s site.', v)
  if (status === 400) return env === 'GEMINI_API_KEY' ? t('{service} did not accept this key (HTTP 400). The key may be wrong, or billing may not be set up for its project.', v)
    : env === 'DASHSCOPE_API_KEY' ? t('{service} did not accept this key (HTTP 400). The account may have an unpaid balance.', v)
    : t('{service} could not read this key (HTTP 400). Copy the whole key again.', v)
  if (typeof status === 'number') return t('{service} answered with an error (HTTP {code}), so the key could not be tested. Try again later.', v)
  return null
}

// What a keyless source's Test measured (P5): only whether a reply came, with its HTTP code, or why none came.
function providerAnswer(test: ProviderTest): string {
  if (test.answered) return t('Answered · HTTP {code}', { code: String(test.http_status) })
  if (test.failure === 'timeout') return t('Did not answer · no reply in {seconds} s', { seconds: String(test.timeout_seconds) })
  if (test.failure === 'connection') return t('Did not answer · no connection')
  return t('Did not answer · {error}', { error: test.error ?? '' })
}

// A tile (mockup `.conn`): the name with its status pill, then one line on what it is. Green only when it can be used.
function Tile({ icon, name, desc, tone, status, active, onClick }: { icon: ReactNode; name: string; desc: string; tone: Tone; status: string; active: boolean; onClick: () => void }) {
  return <button type="button" className={`conn ${active ? 'on' : ''}`} onClick={onClick}>
    <b><span className="conn-title">{icon}<span className="conn-name">{name}</span></span><span className={`st ${tone}`}>{status}</span></b>
    <small>{desc}</small>
  </button>
}

// The mockup's inline confirmation (`.notice.warn` with two buttons) for removing a key.
function RemoveNotice({ text, busy, onRemove, onKeep }: { text: string; busy: boolean; onRemove: () => void; onKeep: () => void }) {
  return <div className="notice warn" role="group" aria-label={t('Remove the key')}>
    <TriangleAlert aria-hidden />
    <div className="nb"><span>{text}</span>
      <div className="acts"><button type="button" className="ghost is-danger" disabled={busy} onClick={onRemove}>{t('Remove')}</button><button type="button" className="ghost" disabled={busy} onClick={onKeep}>{t('Keep it')}</button></div>
    </div>
  </div>
}

// A key field (mockup sheet `key` kind). The stored key is never shown: the field starts empty and its placeholder says
// where the key is kept. Save and test, Test and Remove key report only what the server answered.
function KeyField({ env, entry, keychain, label, service, removeEffect, onSaved, plain = false }: {
  env: string; entry: KeyEntry | undefined; keychain: Keychain; label: string; service: string; removeEffect: string; onSaved: () => void
  plain?: boolean  // an identifier, not a secret: typed in the open and named as an ID
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [asking, setAsking] = useState(false)
  const toast = useToast()
  if (!entry) return null
  const id = `key-${env}`
  if (entry.source === 'environment') return <p className="foot-note">{t('This key comes from the terminal that started DEIXIS; change or remove it there.')}</p>
  const inDotenv = entry.source === 'dotenv'
  if (!entry.configured && !keychain.available) return <p className="foot-note">{t('No system keychain is available.')}</p>
  const where = inDotenv ? '' : t('stored in {keychain}', { keychain: keychain.name ?? t('the system keychain') })
  const typed = value.trim()

  function test() {
    setBusy(true); setFormError('')
    api.testCredential(env).then(result => {
      toast(result.status === 'ok' ? 'success' : 'warning', result.status === 'ok' ? t('The key works.') : serviceErrorSentence({ kind: result.kind, service, resetAt: result.reset_at, effect: 'settings' }))
      onSaved()
    }).catch((e: Error) => setFormError(e.message)).finally(() => setBusy(false))
  }
  function save() {
    setBusy(true); setFormError('')
    api.saveCredential(env, typed).then(result => {
      setValue(''); onSaved()
      toast(result.test && result.test.status !== 'ok' ? 'warning' : 'success', result.test && result.test.status !== 'ok'
        ? t('Key saved, but the service test failed.') + ' ' + serviceErrorSentence({ kind: result.test.kind, service, resetAt: result.test.reset_at, effect: 'settings' })
        : t('Key saved.'))
    }).catch((e: Error) => setFormError(e instanceof ApiError && e.code === 'credential_test_failed'
      ? t('The key was not saved.') + ' ' + (keyRefusal(service, env, e.details?.http_status) ?? serviceErrorSentence({ kind: e.details?.kind, service, resetAt: e.details?.reset_at, effect: 'settings' }))
      : e.message)).finally(() => setBusy(false))
  }
  function remove() {
    setBusy(true); setFormError('')
    api.removeCredential(env).then(() => { setAsking(false); onSaved(); toast('success', t('Key removed.')) })
      .catch((e: Error) => setFormError(e.message)).finally(() => setBusy(false))
  }
  const primary = typed ? (entry.testable ? 'Save and test' : 'Save') : entry.configured && entry.testable ? 'Test' : null
  return <form className="key-box" onSubmit={e => { e.preventDefault(); if (typed) save(); else if (primary) test() }}>
    <label className="lbl" htmlFor={id}>{label}
      <input id={id} className="field" type={plain ? 'text' : 'password'} inputMode={plain ? 'numeric' : undefined} autoComplete="off" spellCheck={false} value={value} disabled={busy}
        placeholder={entry.configured ? `•••••••••••• ${where}`.trim() : t(plain ? 'Type your user ID' : 'Paste your key')} onChange={e => { setValue(e.target.value); setFormError('') }} />
    </label>
    <p className="foot-note">{inDotenv ? t('Never stored in research files or exports.') : t('Stored in {keychain}, never in research files or exports.', { keychain: keychain.name ?? t('the system keychain') })}
      {entry.testable && ` ${t('A new key is tested with one short request before it is saved.')}`}</p>
    {formError && <Notice tone="error"><p>{formError}</p></Notice>}
    <div className="acts">
      {primary && <button type="submit" className="btn-pri" disabled={busy}>{busy ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t(busy ? (typed ? (entry.testable ? 'Testing and saving…' : 'Saving…') : 'Testing…') : primary)}</button>}
      {entry.configured && !asking && <button type="button" className="ghost" disabled={busy} onClick={() => setAsking(true)}>{t(plain ? 'Remove ID' : 'Remove key')}</button>}
    </div>
    {asking && <RemoveNotice busy={busy} onRemove={remove} onKeep={() => setAsking(false)}
      text={t(plain ? 'Remove the ID for {name}?' : 'Remove the key for {name}?', { name: service }) + ' ' + removeEffect} />}
  </form>
}

// Warnings are left out: brew prints them for unrelated taps, so they rarely explain a failed install.
function errorLines(output: string): string[] {
  return output.split('\n').map(line => line.trim()).filter(line => /\berror\b|fatal|npm err!|permission denied|could not|not found/i.test(line)).slice(0, 3)
}

function LocalToolDetails({ tool, dark, onChanged, refresh = true }: { tool: LocalTool; dark: boolean; onChanged: () => Promise<void>; refresh?: boolean }) {
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
  function again() {
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
    {tool.kind === 'cli' && tool.role === 'detected' && <p className="local-tool-note">{t('DEIXIS only checks whether this tool is installed; it never uses it for research.')}</p>}
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
    {refresh && <Button variant="outline" className="connection-recheck" onClick={again} disabled={refreshing}><RefreshCw size={14} />{t(refreshing ? 'Refreshing…' : 'Refresh configuration')}</Button>}
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
function ReaderProgress({ reader }: { reader: EquationReader }) {
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
    <p className="local-tool-note">{t('Marker reads the equations in your PDFs from the page image, so answers and tables get them as LaTeX instead of broken PDF text. It runs on this computer, and no file leaves it.')}</p>
    <p className="local-tool-note">{t('About one Marker equation in fifty was misread in a test on three papers, and a misread equation looks correct. Equations that do not match the PDF’s own text are marked to check against the page.')}</p>
    <dl className="local-tool-facts">
      <dt>{t('Package')}</dt><dd><code className="local-tool-code">{reader.package}</code></dd>
      <dt>{t('License')}</dt><dd>{t('Code GPL-3.0; the models have their own license')}</dd>
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
    <ConfirmDialog open={confirm === 'install'} dark={dark} title={t('Install the equation reader?')} description={t('This downloads Marker and its models (about 4.4 GB) into the DEIXIS data folder, which can take several minutes. Your stored PDFs are then read in the background, which can take hours for a large library.')} context={reader.path} confirmLabel={t('Install')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.installEquationReader)} onOpenChange={open => setConfirm(open ? 'install' : null)} />
    <ConfirmDialog open={confirm === 'remove'} dark={dark} title={t('Remove the equation reader?')} description={t('Marker and its models are deleted. Equations already read stay in the stored text; new PDFs are no longer read.')} confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.removeEquationReader)} onOpenChange={open => setConfirm(open ? 'remove' : null)} />
  </div>
}

// The local OCR tool (D51): detected, not installed by DEIXIS.
function OcrToolDetails({ tool }: { tool: OcrTool }) {
  return <div className="local-tool-details-panel">
    <span className={`status-chip ${tool.available && !tool.missing_languages.length ? '' : 'is-configured'}`}>{t(!tool.available ? 'Not installed' : tool.missing_languages.length ? 'Installed · languages missing' : 'Installed')}</span>
    <p className="local-tool-note">{t('Tesseract reads scanned PDF pages that have no selectable text when you choose Read with OCR on a source. It runs on this computer, no file leaves it, and the PDF is not changed.')}</p>
    <p className="local-tool-note">{t('Text read by OCR is labelled wherever it is quoted. In a test on four scanned articles, 0.2–1.5% of characters were misread and equations were unusable, so check numbers and equations against the page.')}</p>
    <dl className="local-tool-facts">
      <dt>{t('Version')}</dt><dd>{tool.version ?? t('not found')}</dd>
      {tool.available && <><dt>{t('Languages')}</dt><dd>{ocrLanguagesText(tool.languages)}</dd></>}
      {tool.missing_languages.length > 0 && <><dt>{t('Missing')}</dt><dd>{ocrLanguagesText(tool.missing_languages)}</dd></>}
    </dl>
    {tool.reason && <p className="local-tool-note">{tool.reason}</p>}
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
// A translated template whose {name} placeholders are identifiers (model IDs, package names), shown in mono.
const withCode = (template: string, vars: Record<string, string>): ReactNode =>
  template.split(/\{(\w+)\}/).map((part, i) => i % 2 ? <code key={i} className="model-id">{vars[part] ?? part}</code> : part)

function BuiltinEmbeddingPanel({ builtin, dark, onChanged }: { builtin: BuiltinEmbedding; dark: boolean; onChanged: () => Promise<void> }) {
  const [confirm, setConfirm] = useState<'install' | 'remove' | null>(null)
  const [busy, setBusy] = useState(false)
  const [upToDate, setUpToDate] = useState(false)
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
    {builtin.status === 'ready' && upToDate && <p className="local-tool-note" role="status">{t('No update: you have the model this version of DEIXIS uses. Updates come with new versions of DEIXIS.')}</p>}
    {builtin.status === 'update_available' && <>
      <span className="status-chip is-warning">{t('Update available')}</span>
      <p className="local-tool-note">{builtin.available
        ? t('This version of DEIXIS uses a newer copy of the model. The installed copy stays in use until you update.')
        : t('This version of DEIXIS uses a newer copy of the model. The installed copy is not used until you update.')}</p>
    </>}
    {(builtin.status === 'ready' || builtin.status === 'update_available') && <p className="local-tool-note">{withCode(t('Installed: the {model} model, {package} and a Python 3.12 of its own, in the DEIXIS data folder.'), { model: 'BAAI/bge-small-en-v1.5', package: 'fastembed' })}</p>}
    {builtin.status === 'files_do_not_match' && <p className="local-tool-error">{t('The model files do not match the checked copy, so the model is not used. Download them again.')}</p>}
    {builtin.status === 'installing_elsewhere' && <p className="local-tool-note">{t('Another running copy of DEIXIS is downloading it.')}</p>}
    {builtin.status === 'removing' && <p className="local-tool-note">{t('Being removed…')}</p>}
    {builtin.status === 'remove_failed' && <>
      <p className="local-tool-error">{t('Removal did not finish: some files could not be deleted.')}</p>
      {(job?.output ?? '').split('\n').filter(Boolean).slice(0, 4).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
    </>}
    {canDownload && builtin.status !== 'update_available' && <p className="local-tool-note">{t('Needs about {total} MB of disk, plus about {python} MB if Python 3.12 has to be downloaded, plus room for a download cache.', sizeVars)}</p>}
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
      ? <div className="actions"><Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirm('install')}>{t(builtin.status === 'update_available' ? 'Update' : failed || builtin.status === 'files_do_not_match' ? 'Try again' : 'Download')}</Button>
        {builtin.status === 'update_available' && <Button variant="outline" size="sm" className="is-destructive" disabled={busy} onClick={() => setConfirm('remove')}>{t('Remove')}</Button>}</div>
      : <p className="local-tool-note">{builtin.uv.reason}<br /><a href={builtin.uv.url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>)}
    {running && <div className="actions"><Button variant="outline" size="sm" className="is-destructive" disabled={busy} onClick={() => run(api.cancelBuiltinEmbedding)}>{t('Cancel download')}</Button></div>}
    {builtin.status === 'ready' && <div className="actions"><Button variant="outline" size="sm" disabled={busy} onClick={() => run(async () => { await api.checkBuiltinEmbedding(); setUpToDate(true) })}>{t('Check for updates')}</Button>
      <Button variant="outline" size="sm" className="is-destructive" disabled={busy} onClick={() => setConfirm('remove')}>{t('Remove')}</Button></div>}
    {(builtin.status === 'remove_failed' || (builtin.status === 'update_available' && !builtin.uv.available)) && <div className="actions"><Button variant="outline" size="sm" className="is-destructive" disabled={busy} onClick={() => setConfirm('remove')}>{t('Remove')}</Button></div>}
    <ConfirmDialog open={confirm === 'install'} dark={dark} neutral title={t('Download the built-in model?')}
      description={t('The model is downloaded once from Hugging Face and takes about {total} MB in the DEIXIS data folder, plus about {python} MB if Python 3.12 has to be downloaded. After that, semantic search sends no text off this computer.', sizeVars)}
      context={builtin.path} confirmLabel={t('Download')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.installBuiltinEmbedding)} onOpenChange={open => setConfirm(open ? 'install' : null)} />
    <ConfirmDialog open={confirm === 'remove'} dark={dark} title={t('Remove the built-in model?')}
      description={t('Its files are deleted. Scores it already gave are kept; sources not yet scored are ranked without it until you download it again.')}
      confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.removeBuiltinEmbedding)} onOpenChange={open => setConfirm(open ? 'remove' : null)} />
  </div>
}

function GeminiKeyPath() {
  const [before, after] = t('Get a free key: sign in at {link}, create a key, paste it under Cloud models → Gemini.').split('{link}')
  return <p className="local-tool-note">{before}<a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer">aistudio.google.com/apikey</a>{after}</p>
}

// A .bib or .ris file into the Library (F14, S19b's route). The sheet reports what the server stored, entry by entry
// counted from its answer: saved, already saved, confirmed by a provider, kept as the person's own record, unreadable.
function ReferenceFileImport() {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ReferenceImport | null>(null)
  const [error, setError] = useState('')
  const choose = (file: File | undefined) => {
    if (!file || busy) return
    setBusy(true); setError(''); setResult(null)
    libraryImportsApi.referenceFile(file).then(answer => setResult(answer.reference_import))
      .catch((e: Error) => setError(e instanceof ApiError && e.code === 'import_no_entries'
        ? t('Nothing was imported: no entry in the file could be read.') : t('Nothing was imported: {message}', { message: e.message })))
      .finally(() => { setBusy(false); if (input.current) input.current.value = '' })
  }
  const entries = result?.entries ?? []
  const confirmed = entries.filter(e => e.record === 'provider' || e.record === 'existing').length
  const own = entries.filter(e => e.record === 'user_supplied').length
  return <div className="reference-import">
    <input ref={input} type="file" accept=".bib,.ris,.bibtex,text/plain" hidden onChange={e => choose(e.target.files?.[0])} />
    <div className="acts"><button type="button" className="btn-pri" disabled={busy} onClick={() => input.current?.click()}>{busy ? <span className="spin" aria-hidden /> : <Upload aria-hidden />}{t(busy ? 'Importing…' : 'Choose a .bib or .ris file')}</button></div>
    {error && <p className="key-form-error" role="alert">{error}</p>}
    {result && <div className="reference-result" role="status">
      <p>{t('{file}: {n} entries read. {saved} saved to the Library, {already} were already there.', { file: result.filename ?? t('The file'), n: entries.length, saved: result.saved.length, already: result.already_saved.length })}</p>
      <p>{t('{confirmed} matched a provider record by DOI; {own} kept as your own records, not confirmed by a provider.', { confirmed, own })}</p>
      {result.errors.length > 0 && <>
        <p>{t('{n} entries could not be read and were left out:', { n: result.errors.length })}</p>
        <ul>{result.errors.slice(0, 20).map((err, i) => <li key={i}>{t('Line {line}', { line: err.line })}{err.key ? ` · ${err.key}` : ''}: {err.message}</li>)}</ul>
      </>}
    </div>}
  </div>
}

// The sections of the Settings page that read connections (plan ST4–ST8 and the Cloud models placement of §2.2): Cloud
// models, On this computer, Semantic search, the institutional access block given by the page, Scholarly sources and
// Reference managers, with the connection sheet.
export function ConnectionsTab({ dark, access, onConnections, openProvider }: { dark: boolean; access: ReactNode; onConnections?: (connections: Connections) => void; openProvider?: string }) {
  const [data, setData] = useState<Connections | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Selected | null>(null)
  const [open, setOpen] = useState(false)
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [tools, setTools] = useState<LocalTools | null>(null)
  const [toolsError, setToolsError] = useState('')
  const [reader, setReader] = useState<EquationReader | null>(null)
  const [ocrTool, setOcrTool] = useState<OcrTool | null>(null)
  const [semantic, setSemantic] = useState<SemanticSearch | null>(null)
  const [semError, setSemError] = useState('')
  const [pending, setPending] = useState<{ provider: SemanticSearchProvider; model: string | null } | null>(null)
  const [builtin, setBuiltin] = useState<BuiltinEmbedding | null>(null)
  // What this sheet checked itself, and when the answer came: "checked HH:MM" belongs to that answer only.
  const [checking, setChecking] = useState<string | null>(null)
  const [checked, setChecked] = useState<Record<string, number>>({})
  const [checkFailed, setCheckFailed] = useState<Record<string, string>>({})
  const [signIn, setSignIn] = useState<string | null>(null)
  // The sign-in DEIXIS started for a tool (D21); it is polled while the person finishes it in the terminal window that opened.
  const [signInRun, setSignInRun] = useState<{ tool: string; run: AccountSignIn } | null>(null)
  // The last answer to each keyless source's Test; shown only while its check's time is (the same check's answer).
  const [providerTests, setProviderTests] = useState<Record<string, ProviderTest>>({})
  const toast = useToast()
  // A later read wins: an answer to an earlier request that arrives after it is dropped. Semantic search reads and saves
  // share one version: a save moves it on, so a read started before or during the save never replaces the saved result.
  const seq = useRef({ connections: 0, tools: 0, semantic: 0, semanticVersion: 0, saving: false })

  const load = useCallback((refresh: boolean) => {
    const n = ++seq.current.connections
    return api.connections(refresh).then(result => { if (n === seq.current.connections) { setData(result); setError('') } })
      .catch((e: Error) => { if (n === seq.current.connections) setError(t('Connections could not be read: {message}', { message: e.message })) })
  }, [])
  const loadCredentials = useCallback(() => { api.credentials().then(setCredentials).catch((e: Error) => setError(t('Stored keys could not be read: {message}', { message: e.message }))) }, [])
  // A read that a check asked for (`strict`) rejects when it fails, so the check is reported as not run, never as a fresh
  // result over the old state. It resolves false when a later read replaced it (the check then shows no time either).
  const loadTools = useCallback((refresh: boolean, strict = false): Promise<boolean> => {
    const n = ++seq.current.tools
    return api.localTools(refresh).then(result => { if (n !== seq.current.tools) return false; setTools(result); setToolsError(''); return true })
      .catch((e: Error) => { if (n === seq.current.tools) setToolsError(e.message); if (strict) throw e; return false })
  }, [])
  const loadReader = useCallback((strict = false): Promise<boolean> => api.equationReader().then(result => { setReader(result); return true })
    .catch((e: Error) => { setToolsError(e.message); if (strict) throw e; return false }), [])
  const loadOcr = useCallback((strict = false): Promise<boolean> => api.ocr().then(result => { setOcrTool(result); return true })
    .catch((e: Error) => { setToolsError(e.message); if (strict) throw e; return false }), [])
  const loadSemantic = useCallback((strict = false): Promise<boolean> => {
    const n = ++seq.current.semantic, version = seq.current.semanticVersion, duringSave = seq.current.saving
    const current = () => n === seq.current.semantic && version === seq.current.semanticVersion && !duringSave
    return api.semanticSearch().then(result => { if (!current()) return false; setSemantic(result); setSemError(''); return true })
      .catch((e: Error) => { if (current()) setSemError(e.message); if (strict) throw e; return false })
  }, [])
  const loadBuiltin = useCallback(() => api.builtinEmbedding().then(setBuiltin).catch((e: Error) => setSemError(e.message)), [])
  useEffect(() => { void load(false) }, [load])
  useEffect(() => { loadCredentials() }, [loadCredentials])
  useEffect(() => { void loadTools(false) }, [loadTools])
  useEffect(() => { void loadSemantic() }, [loadSemantic])
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
  useEffect(() => {
    if (!tools?.tools.some(tool => tool.job?.status === 'running')) return
    const timer = window.setInterval(() => { void loadTools(false) }, 2000)
    return () => window.clearInterval(timer)
  }, [tools, loadTools])

  const reloadTools = useCallback(() => loadTools(true).then(() => undefined), [loadTools])
  const reloadReader = useCallback(() => loadReader().then(() => undefined), [loadReader])
  const reloadAfterKeyChange = useCallback(() => { loadCredentials(); void load(true); void loadSemantic() }, [loadCredentials, load, loadSemantic])
  // The page's default model choices follow the same connections answer (after a key change or a test).
  useEffect(() => { if (data) onConnections?.(data) }, [data, onConnections])

  // A check this sheet asked for: the button stays locked until its answer, and the time shown is that answer's.
  const runCheck = (key: string, check: () => Promise<unknown>) => {
    if (checking) return
    setChecking(key)
    const drop = <T,>(old: Record<string, T>) => { const next = { ...old }; delete next[key]; return next }
    void check().then(result => {
      // A read replaced by a later one is not this check's answer: no time, no failure.
      if (result === false || (Array.isArray(result) && result.includes(false))) return
      // A check whose answer carries the server's own time (a keyless source's Test) shows that time.
      const at = result && typeof result === 'object' && 'checked_at' in result ? Date.parse(String(result.checked_at)) : NaN
      setChecked(old => ({ ...old, [key]: Number.isNaN(at) ? Date.now() : at })); setCheckFailed(drop)
    }, (e: Error) => { setChecked(drop); setCheckFailed(old => ({ ...old, [key]: e.message })) })
      .finally(() => setChecking(current => current === key ? null : current))
  }
  const refreshModel = (id: string) => api.modelConnection(id, true).then(result => {
    setData(current => current ? { ...current, models: { ...current.models, [id]: result } } : current)
  }).catch((e: Error) => { toast('error', t('Check failed: {message}', { message: e.message })); throw e })
  const settleSignIn = useCallback((tool: string, run: AccountSignIn) => {
    setSignInRun(current => current && current.tool !== tool ? current : { tool, run })
    if (run.state !== 'succeeded') return
    toast('success', t('Signed in to {name}.', { name: ACCOUNT_TOOLS[tool]?.name ?? tool }))
    void api.modelConnection(tool, true).then(result => {
      setData(current => current ? { ...current, models: { ...current.models, [tool]: result } } : current)
    }).catch(() => undefined)
    void loadTools(true)
  }, [toast, loadTools])
  const startSignIn = (tool: string) => {
    api.startAccountSignIn(tool).then(run => settleSignIn(tool, run), (e: Error) => {
      setSignInRun({ tool, run: { state: 'failed', message: e.message } })
      setSignIn(tool)
      toast('error', t('Could not start the sign-in: {message}', { message: e.message }))
    })
  }
  const signInTool = signInRun?.run.state === 'waiting' ? signInRun.tool : null
  useEffect(() => {
    if (!signInTool) return
    const timer = window.setInterval(() => {
      api.accountSignIn(signInTool).then(run => settleSignIn(signInTool, run), () => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [signInTool, settleSignIn])
  const show = (item: Selected) => { setSelected(item); setOpen(true); setSignIn(null) }
  // A link to one provider's sheet (`#/settings/openalex`) opens it once the providers are read.
  const opened = useRef(false)
  useEffect(() => {
    if (!openProvider || opened.current || !data?.providers?.some(p => p.id === openProvider)) return
    opened.current = true
    setSelected({ kind: 'provider', id: openProvider }); setOpen(true)
  }, [openProvider, data])
  const isActive = (kind: Selected['kind'], id: string) => open && !gone && selected?.kind === kind && selected.id === id
  const check = (label: string, value: string) => <div className="legacy-check" key={label}><span>{label}</span><strong>{value}</strong></div>

  const modelEntries = Object.entries(data?.models ?? {})
  const cloudModels = modelEntries.filter(([id]) => !ACCOUNT_TOOLS[id])
  const toolOf = (id: string) => tools?.tools.find(tool => tool.id === id)
  const otherCli = (tools?.tools ?? []).filter(tool => tool.kind === 'cli' && tool.id !== 'codex' && tool.id !== 'claude_code')
  const servers = (tools?.tools ?? []).filter(tool => SERVER_IDS.includes(tool.id))
  const zotero = toolOf('zotero')
  const machine = tools?.machine
  const providers = [...(data?.providers ?? [])].sort((a, b) => {
    const rank = (id: string) => { const i = PROVIDER_ORDER.indexOf(id); return i < 0 ? PROVIDER_ORDER.length : i }
    return rank(a.id) - rank(b.id)
  })
  const openaiKey = credentials?.keys.find(k => k.env === 'OPENAI_API_KEY')
  const keyEntry = (env: string) => credentials?.keys.find(k => k.env === env)

  // A sheet whose subject is no longer listed closes; one still loading stays.
  const gone = !!selected && (selected.kind === 'model' ? !!data && !data.models[selected.id]
    : selected.kind === 'provider' ? !!data && !data.providers.some(p => p.id === selected.id)
    : selected.kind === 'cli' || selected.kind === 'zotero' ? !!tools && !tools.tools.some(tool => tool.id === selected.id)
    : selected.kind === 'account' ? !!data && !!tools && !data.models[selected.id] && !tools.tools.some(tool => tool.id === ACCOUNT_TOOLS[selected.id]?.tool)
    : false)

  const modelStatus = (m: ModelHealth): [Tone, string] => m.ready ? ['ok', t('Ready')]
    : m.key_configured === false ? ['no', t('Not set up')]
    : m.signed_in === false && m.installed ? ['no', t('Not signed in')]
    : m.installed === false && m.key_configured === undefined ? ['no', t('Not installed')]
    : ['warn', t('Not ready')]
  const loading: [Tone, string] = ['no', t('Checking…')]
  const unknown: [Tone, string] = ['no', t('Not known')]
  const accountStatus = (id: string): [Tone, string] => {
    const model = data?.models[id]
    if (model) return modelStatus(model)
    const tool = toolOf(ACCOUNT_TOOLS[id].tool)
    if (tool) return tool.installed ? ['no', t('Installed')] : ['no', t('Not installed')]
    return (!data || !tools) && !error && !toolsError ? loading : unknown
  }
  const serversStatus = (): [Tone, string] => {
    if (!tools) return toolsError ? unknown : loading
    if (servers.some(s => s.running)) return ['ok', t('Running')]
    return servers.some(s => s.installed) ? ['no', t('Not running')] : ['no', t('Not installed')]
  }
  const ocrStatus = (): [Tone, string] => !ocrTool ? (toolsError ? unknown : loading)
    : !ocrTool.available ? ['no', t('Not installed')] : !ocrTool.missing_languages.length ? ['ok', t('Installed')]
    : ['warn', t(ocrTool.languages.join() === 'eng' ? 'English only' : 'Languages missing')]
  const readerStatus = (): [Tone, string] => !reader ? (toolsError ? unknown : loading)
    : reader.job?.status === 'running' ? ['no', t('Installing…')] : reader.installed && reader.models_downloaded ? ['ok', t('Installed')] : ['no', t('Not installed')]
  const providerStatus = (mode: string | null): [Tone, string] => mode === 'api_key' ? ['ok', t('Key configured')] : mode === 'keyless' ? ['ok', t('No key needed')] : ['no', t('Not set up')]
  const zoteroStatus = (): [Tone, string] => !zotero ? (tools ? ['no', t('Not set up')] : toolsError ? unknown : loading)
    : zotero.running && zotero.local_api ? ['ok', t('Local API on')] : zotero.web_configured ? ['ok', t('zotero.org set')]
    : zotero.installed ? ['no', t(zotero.running ? 'Local API off' : 'Not running')] : ['no', t('Not set up')]
  const modelDesc = (id: string) => id === 'gemini' ? t('API key · models and semantic search') : id === 'ollama' ? t('This computer · no key') : compatConnectionKeys[id] ? t('API key · not tested with the real service yet') : t('API key')
  const tile = (key: string, kind: Selected['kind'], id: string, name: string, desc: string, [tone, status]: [Tone, string]) =>
    <Tile key={key} icon={settingsIcon(key)} name={name} desc={desc} tone={tone} status={status} active={isActive(kind, id)} onClick={() => show({ kind, id })} />

  // Semantic search rows (plan ST5): the mockup's five, one "Local model server" for Ollama and LM Studio. A row that
  // cannot be chosen says what it needs, from the options' own state. A choice is saved at once; choosing the row that
  // is only the default (nothing saved yet) saves it too.
  const option = (p: SemanticSearchProvider) => semantic?.options.find(o => o.provider === p)
  const serverOptions = SERVER_IDS.map(id => option(id as SemanticSearchProvider)).filter((o): o is SemanticSearchOption => !!o)
  const serverChoices = serverOptions.filter(o => o.available).flatMap(o => o.models.map(m => ({ provider: o.provider, model: m, label: `${o.provider === 'ollama' ? 'Ollama' : 'LM Studio'} · ${m}` })))
  const chosen = pending ?? (semantic ? { provider: semantic.provider, model: semantic.model } : null)
  const saving = pending !== null
  const serverChosen = !!chosen && SERVER_IDS.includes(chosen.provider)
  function chooseSemantic(provider: SemanticSearchProvider, model: string | null) {
    if (saving || !semantic) return
    const version = ++seq.current.semanticVersion
    seq.current.saving = true
    setPending({ provider, model })
    api.saveSemanticSearch(provider, model).then(result => {
      if (version !== seq.current.semanticVersion) return
      seq.current.semantic++  // reads started before the save are dropped
      setSemantic(result); setSemError(''); toast('success', t('Semantic search setting saved.'))
    }).catch((e: Error) => { if (version === seq.current.semanticVersion) toast('error', t('Could not save: {message}', { message: e.message })) })
      .finally(() => { if (version === seq.current.semanticVersion) { seq.current.saving = false; setPending(null) } })
  }
  const needsPill = (row: string): string | null => {
    if (!semantic) return null
    if (row === 'gemini') return option('gemini')?.available ? null : t('Needs a Google AI key')
    if (row === 'openai') return option('openai')?.available ? null : t('Needs an OpenAI key')
    if (row === 'builtin') { const o = option('builtin'); return o && !o.available ? t(o.reason ?? 'Not downloaded') : null }
    if (row === 'server') return serverChoices.length ? null : serverOptions.some(o => /lists no embedding model/.test(o.reason ?? '')) ? t('Needs an embedding model') : t('Needs a local server')
    return null
  }
  const semanticRows: { id: string; label: string; desc?: ReactNode; providers: SemanticSearchProvider[]; body?: ReactNode }[] = [
    { id: 'builtin', providers: ['builtin'], label: t('This computer · built-in'),
      body: <>
        {builtin && <BuiltinEmbeddingPanel builtin={builtin} dark={dark} onChanged={async () => { await loadBuiltin(); await loadSemantic() }} />}
      </> },
    { id: 'openai', providers: ['openai'], label: t('OpenAI embeddings'),
      desc: withCode(t('{model} · sends titles, abstracts and passage text to OpenAI'), { model: option('openai')?.models[0] ?? 'text-embedding-3-small' }) },
    { id: 'gemini', providers: ['gemini'], label: t('Gemini embeddings'),
      desc: withCode(t('{model} · sends titles, abstracts and passage text to Google'), { model: option('gemini')?.models[0] ?? 'gemini-embedding' }),
      body: <>
        <p className="local-tool-note">{t('Reads the question in any language. Needs a Google AI Studio key; a free key works.')}</p>
        {!option('gemini')?.available && <GeminiKeyPath />}
      </> },
    { id: 'server', providers: ['ollama', 'lm_studio'], label: t('Local model server'), desc: t('An embedding model on Ollama or LM Studio') },
    { id: 'off', providers: ['off'], label: t('Off'), desc: t('Keyword search only; sources get no similarity score.') },
  ]
  const privacy = !semantic ? null : semantic.provider === 'off' ? t('Sources get no similarity score; passages are ranked by keyword match only. No text is sent anywhere.')
    : semantic.provider === 'gemini' ? t('Passage text is sent to Google. If your key is on Google’s free tier, which DEIXIS cannot detect, Google may use that text to improve its products.')
    : semantic.provider === 'openai' ? t('Passage text is sent to {service}.', { service: 'OpenAI' })
    : semantic.provider === 'builtin' ? t('For semantic search, no text leaves the computer.') : t('Passage text stays on this computer.')

  // ---- the connection sheet ----
  const sel = selected
  const accountId = sel?.kind === 'account' ? sel.id : null
  const model = sel?.kind === 'model' ? data?.models[sel.id] : accountId ? data?.models[accountId] : undefined
  const provider = sel?.kind === 'provider' ? data?.providers.find(p => p.id === sel.id) : undefined
  const cliTool = sel?.kind === 'cli' ? toolOf(sel.id) : accountId ? toolOf(ACCOUNT_TOOLS[accountId].tool) : undefined
  // The sheet title carries the same icon as the tile it opened from.
  const sheetIconKey = !sel ? '' : sel.kind === 'api-key' ? 'openai' : sel.kind === 'ocr-tool' ? 'ocr' : sel.kind === 'reference-files' ? 'reference-files' : sel.id
  const name = !sel ? ''
    : sel.kind === 'account' ? ACCOUNT_TOOLS[sel.id]?.name ?? sel.id
    : sel.kind === 'model' ? modelNames[sel.id] ?? sel.id
    : sel.kind === 'provider' ? providerNames[sel.id] ?? sel.id
    : sel.kind === 'api-key' ? t('OpenAI API')
    : sel.kind === 'equation-reader' ? t('Equation reader (Marker)')
    : sel.kind === 'ocr-tool' ? t('OCR (Tesseract)')
    : sel.kind === 'servers' ? t('Local model servers')
    : sel.kind === 'reference-files' ? t('BibTeX / RIS files')
    : sel.kind === 'zotero' ? 'Zotero'
    : cliTool?.name || localToolNames[sel.id] || sel.id
  const checkedLine = (key: string) => checked[key] && !checkFailed[key] ? <span className="status-chip is-configured">{t('checked {time}', { time: clock(checked[key]) })}</span> : null
  // A failed check and the reason a connection is not ready share one card under the status line.
  const dmeta = (key: string, [tone, status]: [Tone, string], extra?: ReactNode, reason?: ReactNode) => {
    const failed = checking !== key && checkFailed[key]
    return <>
      <p className="dmeta">{checking === key ? <span><span className="spin" aria-hidden /> {t('Checking…')}</span> : <span className={`status-chip is-status ${tone === 'warn' ? 'is-warning' : tone === 'no' ? 'is-configured' : ''}`}>{status}</span>}{extra}{checking !== key && checkedLine(key)}</p>
      {(failed || reason) && <Notice tone="attention">
        {failed && <p className="check-failed">{t('Could not check: {message}', { message: checkFailed[key] })}</p>}
        {reason && <p>{reason}</p>}
      </Notice>}
    </>
  }
  const checkButton = (key: string, label: string, run: () => Promise<unknown>, disabled = false) =>
    <button type="button" className="btn-pri" disabled={disabled || checking !== null} onClick={() => runCheck(key, run)}>{checking === key ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t(label)}</button>
  // The Codex home this backend uses (DEIXIS_CODEX_HOME or the data folder's), single-quoted for a POSIX shell.
  const codexLogin = data?.codex_home ? `CODEX_HOME='${data.codex_home.replaceAll("'", "'\\''")}' codex login` : null
  const signInCommand = accountId === 'codex' ? codexLogin : accountId === 'claude' ? 'claude auth login' : null
  const copy = (text: string) => { writeClipboard(text).then(() => toast('success', t('Command copied.')), () => toast('error', t('Could not copy; select the command and copy it.'))) }

  const keyedSheet = (env: string, service: string, effect: string) => credentials && <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain}
    label={t('API key')} service={service} removeEffect={effect} onSaved={reloadAfterKeyChange} />

  let body: ReactNode = null
  if (sel?.kind === 'account' && accountId) {
    const key = `account:${accountId}`
    const ownRun = signInRun?.tool === accountId ? signInRun.run : null
    body = <>
      {dmeta(key, accountStatus(accountId), undefined, model && !model.ready ? healthReasonText(model) : undefined)}
      <p className="foot-note is-ink">{t(accountId === 'codex'
        ? 'Uses the account you sign in with through Codex CLI. DEIXIS keeps this sign-in apart from your usual Codex one and stores no password.'
        : 'Uses the account you are signed in with in Claude Code. DEIXIS keeps no password or token of its own.')}</p>
      <div className="acts">
        {checkButton(key, 'Test the connection', () => refreshModel(accountId), !model)}
        {signInCommand && <button type="button" className="ghost" disabled={ownRun?.state === 'waiting'} onClick={() => startSignIn(accountId)}>
          {ownRun?.state === 'waiting' && <span className="spin" aria-hidden />}
          {ownRun && (ownRun.state === 'failed' || ownRun.state === 'timed_out') ? t('Try again') : model?.signed_in ? t('Sign in again') : t('Sign in')}
        </button>}
      </div>
      {ownRun?.state === 'waiting' && <p className="foot-note signin-wait" role="status">
        <span className="spin" aria-hidden />{t('A terminal window opened. Finish signing in there; this updates by itself.')}
      </p>}
      {ownRun && (ownRun.state === 'failed' || ownRun.state === 'timed_out') && ownRun.message && <p className="foot-note warn-t" role="alert">{ownRun.message}</p>}
      {signInCommand && <button type="button" className="ghost" aria-expanded={signIn === accountId} onClick={() => setSignIn(signIn === accountId ? null : accountId)}>{t('Or run this in a terminal')}</button>}
      {signIn === accountId && signInCommand && <div className="signin-cmd">
        <p className="foot-note">{t('Run this in a terminal, then test the connection:')}</p>
        <div className="cmd-row"><code className="field mono">{signInCommand}</code><button type="button" className="ghost" onClick={() => copy(signInCommand)}><Copy aria-hidden />{t('Copy')}</button></div>
      </div>}
      {model && accountId === 'codex' && <>
        <p className="foot-note">{t('Codex only writes text for DEIXIS: its tools, add-ons and instruction files are turned off.')}</p>
        <div className="connection-checks">
          {check('CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
          {check(t('Signed in for DEIXIS'), model.signed_in ? t('yes · {plan}', { plan: model.plan_type ?? model.account_type ?? '' }) : t('no'))}
          {check(t('Instruction files used'), model.isolation ? String(model.isolation.instruction_sources) : t('not checked'))}
          {check(t('Add-ons with tools'), model.isolation ? (model.isolation.live_mcp_servers.join(', ') || t('none')) : t('not checked'))}
        </div>
      </>}
      {model && accountId === 'claude' && <>
        <p className="foot-note">{t('Claude Code only writes text for DEIXIS: its tools, add-ons and instruction files are turned off.')}</p>
        <div className="connection-checks">
          {check('CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
          {check(t('Signed in to Claude Code'), model.signed_in ? t('yes · {plan}', { plan: model.plan_type ?? model.account_type ?? '' }) : t('no'))}
          {check(t('Instruction files used'), model.isolation ? String(model.isolation.instruction_sources) : t('not checked'))}
          {check(t('Add-ons with tools'), model.isolation ? (model.isolation.live_mcp_servers.join(', ') || t('none')) : t('not checked'))}
        </div>
      </>}
      {model && <ModelCatalogue model={model} />}
      {!model && data && <p className="foot-note">{t('No model connection is set up for it in this version of DEIXIS; the tool on this computer is shown below.')}</p>}
      {cliTool && (!model || !cliTool.installed) && <LocalToolDetails key={cliTool.id} tool={cliTool} dark={dark} onChanged={reloadTools} />}
    </>
  } else if (sel?.kind === 'model' && model) {
    const env = sel.id === 'gemini' ? 'GEMINI_API_KEY' : sel.id === 'deepseek' ? 'DEEPSEEK_API_KEY' : compatConnectionKeys[sel.id]
    const key = `model:${sel.id}`
    body = <>
      {dmeta(key, modelStatus(model), undefined, !model.ready && model.key_configured !== false ? healthReasonText(model) : undefined)}
      {env && keyedSheet(env, modelNames[sel.id] ?? sel.id, t('This connection stops working until a new key is added.'))}
      {sel.id === 'gemini' && <>
        <div className="connection-checks">
          {/* From the saved semantic search provider, not from the key alone: another provider or Off may be chosen. */}
          {check(t('Semantic passage search'), !semantic ? t('not known') : semantic.provider === 'gemini' ? t('on · passage text is sent to Google')
            : model.key_configured ? t('off · another provider is chosen') : t('off'))}
        </div>
      </>}
      {sel.id === 'ollama' && <p className="foot-note">{t('DEIXIS uses Ollama on this computer, so no key is needed. Open the Ollama app or run `ollama serve`, then download a model with `ollama pull`.')}</p>}
      <div className="acts">{checkButton(key, 'Check again', () => refreshModel(sel.id))}</div>
      <ModelCatalogue model={model} />
    </>
  } else if (sel?.kind === 'api-key') {
    body = <>
      {dmeta('api-key', openaiKey?.configured ? ['ok', t('Key configured')] : ['no', t('Not set up')])}
      <p className="foot-note is-ink">{t('Used for semantic search only, when OpenAI embeddings are chosen.')}</p>
      {keyedSheet('OPENAI_API_KEY', 'OpenAI', t('Semantic search with OpenAI stops until a new key is added.'))}
    </>
  } else if (sel?.kind === 'provider' && provider) {
    const env = providerKeyEnv[provider.id]
    const [tone, status] = providerStatus(provider.access_mode)
    const key = `provider:${provider.id}`
    const keyless = provider.access_mode === 'keyless'
    const test = keyless && checking !== key && checked[key] && !checkFailed[key] ? providerTests[provider.id] : undefined
    const id = provider.id
    body = <>
      {dmeta(key, [tone, status], test && <span className={`status-chip ${test.answered && (test.http_status ?? 0) < 300 ? '' : 'is-warning'}`}>{providerAnswer(test)}</span>)}
      <p className="foot-note is-ink">{provider.id === 'openalex'
        ? t('Works without a key. A free key from openalex.org gives DEIXIS its own daily budget.')
        : !env ? (MAILTO_PROVIDERS.has(provider.id) ? t('No key needed. DEIXIS adds your contact email to its requests, as the service asks.') : t('No key needed.'))
        : t(provider.note)}</p>
      {env && credentials && <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain} service={providerNames[provider.id] ?? provider.id}
        label={t(provider.id === 'openalex' ? 'API key (optional, free from openalex.org)' : 'API key')}
        removeEffect={t('Requests that need this key stop until you add one again.')} onSaved={reloadAfterKeyChange} />}
      {env && credentials && !keyEntry(env)?.configured && providerNoKey[provider.id] && <Notice tone="attention">{t(providerNoKey[provider.id])}</Notice>}
      {keyless && <div className="acts">{checkButton(key, 'Test', () => api.testProvider(id).then(result => { setProviderTests(old => ({ ...old, [id]: result })); return result }))}</div>}
      {test && !test.contact_email_sent && <p className="foot-note">{t('Sent without a contact email; none is set in Profile.')}</p>}
      {MAILTO_PROVIDERS.has(provider.id) && <p className="foot-note"><a href="#/settings/profile">{t('Set the contact email in Profile')}</a></p>}
      <div className="connection-checks">{check(t('Used for'), providerUse[provider.id] ? t(providerUse[provider.id]) : providerRole(provider.role))}</div>
    </>
  } else if (sel?.kind === 'cli' && cliTool) {
    body = <LocalToolDetails key={cliTool.id} tool={cliTool} dark={dark} onChanged={reloadTools} />
  } else if (sel?.kind === 'servers') {
    body = <>
      {dmeta('servers', serversStatus())}
      <p className="foot-note is-ink">{t('Ollama and LM Studio run models on this computer. Semantic search can use one of their embedding models, and Ollama models can also run research steps.')}</p>
      {servers.map(server => <section key={server.id} className="server-block" aria-label={server.name || localToolNames[server.id]}>
        <h3>{server.name || localToolNames[server.id]}</h3>
        {server.endpoint && <div className="lbl">{t('Server address')}<code className="field mono">{server.endpoint}</code></div>}
        <LocalToolDetails tool={server} dark={dark} onChanged={reloadTools} refresh={false} />
      </section>)}
      {servers.some(server => server.endpoint) && <p className="foot-note">{t('Each address is the one its app uses by default; this version of DEIXIS cannot change it.')}</p>}
      {/* The same choice as the Local model server row on the page: choosing a model saves it as the semantic search provider. */}
      <label className="lbl">{t('Embedding model for semantic search')}
        <select className="select server-embedding" disabled={saving || !serverChoices.length} value={serverChosen ? `${chosen!.provider}|${chosen!.model ?? ''}` : ''}
          onChange={e => { if (!e.target.value) return; const [p, ...m] = e.target.value.split('|'); chooseSemantic(p as SemanticSearchProvider, m.join('|')) }}>
          {!serverChosen && <option value="">{t(serverChoices.length ? 'Not used for semantic search' : 'No embedding model listed')}</option>}
          {serverChoices.map(c => <option key={`${c.provider}|${c.model}`} value={`${c.provider}|${c.model}`}>{c.label}</option>)}
        </select>
      </label>
      <div className="acts">{checkButton('servers', 'Test', () => Promise.all([loadTools(true, true), loadSemantic(true)]))}</div>
    </>
  } else if (sel?.kind === 'equation-reader') {
    body = <>
      {dmeta('equation-reader', readerStatus())}
      <p className="foot-note is-ink">{t('Runs on this computer. DEIXIS installs it into its data folder when you choose Install.')}</p>
      <div className="acts">{checkButton('equation-reader', 'Find it on this computer', () => loadReader(true))}</div>
      {reader && <EquationReaderDetails reader={reader} dark={dark} onChanged={reloadReader} />}
    </>
  } else if (sel?.kind === 'ocr-tool') {
    body = <>
      {dmeta('ocr-tool', ocrStatus())}
      <p className="foot-note is-ink">{t('Runs on this computer. Install it once, then test.')}</p>
      <div className="acts">{checkButton('ocr-tool', 'Find it on this computer', () => loadOcr(true))}</div>
      {ocrTool && <OcrToolDetails tool={ocrTool} />}
    </>
  } else if (sel?.kind === 'zotero') {
    body = <>
      {dmeta('zotero', zoteroStatus())}
      <p className="foot-note is-ink">{t('Import a collection from Add sources on the home page or from a research’s Sources panel. Your Zotero library is never changed.')}</p>
      <div className="acts">{checkButton('zotero', 'Find it on this computer', () => loadTools(true, true))}</div>
      {zotero && <LocalToolDetails tool={zotero} dark={dark} onChanged={reloadTools} refresh={false} />}
      {credentials && <>
        <p className="foot-note is-ink">{t('To import from zotero.org, create a read-only key at zotero.org/settings/keys. Your user ID is shown on the same page.')}</p>
        {(['ZOTERO_API_KEY', 'ZOTERO_LIBRARY_ID'] as const).map(env => <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain}
          plain={env === 'ZOTERO_LIBRARY_ID'} label={t(env === 'ZOTERO_API_KEY' ? 'zotero.org API key' : 'zotero.org user ID')} service="zotero.org"
          removeEffect={t('Importing from zotero.org stops until you add it again.')} onSaved={() => { reloadAfterKeyChange(); void reloadTools() }} />)}
      </>}
    </>
  } else if (sel?.kind === 'reference-files') {
    body = <>
      <p className="foot-note is-ink">{t('Adds the entries of a .bib or .ris file to the Library. Entries whose DOI OpenAlex or Crossref confirms use that record; the rest are kept as you wrote them, marked as not confirmed.')}</p>
      <ReferenceFileImport />
    </>
  }

  return <>
    {error && <Notice tone="error">{error}</Notice>}

    <div className="cloud-models" data-panel="models">
    <h2>{t('Cloud models')}</h2>
    <div className="grid3" data-group="cloud">
      {cloudModels.map(([id, m]) => tile(id, 'model', id, modelNames[id] ?? id, modelDesc(id), modelStatus(m)))}
      {tile('openai', 'api-key', 'OPENAI_API_KEY', t('OpenAI API'), t('API key · semantic search only'), !credentials ? loading : openaiKey?.configured ? ['ok', t('Key configured')] : ['no', t('Not set up')])}
    </div>
    </div>

    <h2 id="on-this-computer" tabIndex={-1} data-panel="models">{t('On this computer')}</h2>
    {toolsError && <Notice tone="error" panel="models">{toolsError}</Notice>}
    <div className="grid3" data-group="computer" data-panel="models">
      {tile('codex', 'account', 'codex', 'Codex CLI', t('Account sign-in'), accountStatus('codex'))}
      {tile('claude', 'account', 'claude', 'Claude Code', t('Account sign-in'), accountStatus('claude'))}
      {tile('ocr', 'ocr-tool', 'tesseract', t('OCR (Tesseract)'), t('Scanned PDFs'), ocrStatus())}
      {tile('servers', 'servers', 'servers', t('Local model servers'), t('Ollama or LM Studio · no account'), serversStatus())}
      {tile('marker', 'equation-reader', 'marker', t('Equation reader (Marker)'), t('Reads equations as LaTeX'), readerStatus())}
    </div>
    {otherCli.length > 0 && <div className="computer-more" data-panel="models">
      {otherCli.length > 0 && <details className="planned-connections"><summary><ChevronRight size={14} aria-hidden />{t('Other command-line tools · {n}', { n: otherCli.length })}</summary>
        <p className="foot-note">{t('Only Claude Code and Codex CLI run research steps. The other tools are detected only: finding one here does not mean DEIXIS supports it.')}</p>
        <div className="grid3">{otherCli.map(tool => tile(tool.id, 'cli', tool.id, tool.name || localToolNames[tool.id] || tool.id, t('Detected only'), ['no', t(tool.job?.status === 'running' ? 'Installing…' : tool.installed ? 'Installed' : 'Not installed')]))}</div>
      </details>}
    </div>}

    {machine && (machine.chip || machine.memory_gb != null || machine.disk_free_gb != null) && <>
      <h2 data-panel="models">{t('This computer')}</h2>
      <div className="machine-card" data-group="machine" data-panel="models">
        {machine.chip && <div className="machine-cell"><Cpu size={16} aria-hidden /><p><small>{t('Processor')}</small><b>{machine.chip}</b></p></div>}
        {machine.memory_gb != null && <div className="machine-cell"><MemoryStick size={16} aria-hidden /><p><small>{t('Memory')}</small><b>{machine.memory_gb} GB</b></p></div>}
        {machine.disk_free_gb != null && <div className="machine-cell machine-disk"><HardDrive size={16} aria-hidden /><p><small>{t('Disk')}</small><b>{t('{gb} GB free', { gb: machine.disk_free_gb })}</b>
          {machine.disk_total_gb ? <>
            <span className="bar" role="meter" aria-label={t('Disk used')} aria-valuemin={0} aria-valuemax={machine.disk_total_gb} aria-valuenow={machine.disk_total_gb - machine.disk_free_gb}><i style={{ width: `${Math.round((1 - machine.disk_free_gb / machine.disk_total_gb) * 100)}%` }} /></span>
            <small>{t('{used} GB used of {total} GB', { used: machine.disk_total_gb - machine.disk_free_gb, total: machine.disk_total_gb })}</small>
          </> : null}</p></div>}
      </div>
    </>}
    <DataLocationCard dark={dark} />

    <h2 data-panel="models">{t('Semantic search')}</h2>
    <p className="foot-note" data-panel="models">{t('Ranks search results by meaning, not only by shared words. Changing the provider scores the passages again; earlier scores are kept.')}</p>
    {semError && <Notice tone="error" panel="models">{semError}</Notice>}
    <div className="rows opts semantic-choices" data-panel="models" role="radiogroup" aria-label={t('Semantic search provider')} aria-busy={saving || undefined}>
      {semanticRows.map(row => {
        const isChosen = !!chosen && row.providers.includes(chosen.provider)
        const available = !!semantic && (row.id === 'server' ? serverChoices.length > 0 : !!option(row.providers[0])?.available)
        const need = needsPill(row.id)
        const pick = () => {
          if (row.id === 'server') { const first = serverChoices[0]; if (first) chooseSemantic(first.provider, first.model) }
          else chooseSemantic(row.providers[0], null)
        }
        return <div className="semantic-option" key={row.id} data-row={row.id}>
          <label className={!available ? 'is-disabled' : undefined}>
            <input type="radio" name="semantic-provider" checked={isChosen} disabled={!available || saving} onChange={pick}
              onClick={() => { if (isChosen && semantic && !semantic.explicit) pick() }} />
            {settingsIcon(row.id)}<span>{row.label}{row.desc && <small>{row.desc}</small>}</span>
            {saving && isChosen && <span className="spin" aria-label={t('Saving…')} />}
            {need && <span className="st no">{need}</span>}
          </label>
          {row.id === 'server' && isChosen && serverChoices.length > 0 && <div className="semantic-option-body">
            <select className="select semantic-model" aria-label={t('Embedding model')} disabled={saving} value={`${chosen?.provider}|${chosen?.model ?? ''}`}
              onChange={e => { const [p, ...m] = e.target.value.split('|'); chooseSemantic(p as SemanticSearchProvider, m.join('|')) }}>
              {serverChoices.map(c => <option key={`${c.provider}|${c.model}`} value={`${c.provider}|${c.model}`}>{c.label}</option>)}
            </select>
          </div>}
          {row.body && <div className="semantic-option-body">{row.body}</div>}
        </div>
      })}
    </div>
    {privacy && <p className="foot-note semantic-privacy" data-panel="models">{privacy}</p>}

    {access}

    <h2 data-panel="sources">{t('Scholarly sources')}</h2>
    <div className="grid3" data-group="sources" data-panel="sources">{providers.map(p => tile(p.id, 'provider', p.id, providerNames[p.id] ?? p.id, providerUse[p.id] ? t(providerUse[p.id]) : providerRole(p.role), providerStatus(p.access_mode)))}</div>
    <p className="foot-note sources-note" data-panel="sources">{t('New researches use every source that has the access it needs.')}</p>

    <h2 data-panel="sources">{t('Reference managers')}</h2>
    <div className="grid3" data-group="references" data-panel="sources">
      {tile('zotero', 'zotero', 'zotero', 'Zotero', t('Read-only collections'), zoteroStatus())}
      {tile('reference-files', 'reference-files', 'files', t('BibTeX / RIS files'), t('Import a .bib or .ris file'), ['ok', t('Available')])}
    </div>

    <Sheet open={open && !gone} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet connection-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader><SheetTitle>{(sheetIconKey && settingsIcon(sheetIconKey)) || <Link size={16} aria-hidden />}<span>{name}</span></SheetTitle><SheetDescription className="sr-only">{t('{name} details', { name })}</SheetDescription></SheetHeader>
        <div className="connection-body mk pad detail">{body}</div>
      </SheetContent>
    </Sheet>
  </>
}
