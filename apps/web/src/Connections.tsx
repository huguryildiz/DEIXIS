import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronRight, Copy, Link, LoaderCircle, RefreshCw, RotateCw, TriangleAlert, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ConfirmDialog } from './ConfirmDialog'
import { api, ApiError, libraryImportsApi, shellApi, type BuiltinEmbedding, type Connections, type ContactEmailSetting, type Credentials, type KeyEntry, type Keychain, type EquationReader, type LocalTool, type OcrTool, type LocalTools, type ModelHealth, type ReferenceImport, type SemanticSearch, type SemanticSearchOption, type SemanticSearchProvider } from './api'
import { useToast } from './Toast'
import { ocrLanguagesText } from './ocr'
import { t, uiLocale } from './i18n'
import { serviceErrorSentence, healthReasonText, compatConnectionKeys, connectionNames as modelNames, isPlannedModel, localToolNames, providerRole, reasoningLabel } from './labels'
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
// Sources whose requests carry the contact email as `mailto` (openalex.py, crossref.py).
const MAILTO_PROVIDERS = new Set(['openalex', 'crossref'])
// The model connections that sign in with an account on this computer, and the command-line tool each one runs.
const ACCOUNT_TOOLS: Record<string, { tool: LocalTool['id']; name: string }> = { codex: { tool: 'codex', name: 'Codex CLI' }, claude: { tool: 'claude_code', name: 'Claude Code' } }
const SERVER_IDS = ['ollama', 'lm_studio']
const formatBytes = (bytes: number) => bytes / 1e9 >= 1 ? t('{gb} GB', { gb: (bytes / 1e9).toFixed(1) }) : t('{mb} MB', { mb: Math.round(bytes / 1e6) })
const clock = (iso: string | number) => new Date(iso).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })

type Selected = { kind: 'account' | 'model' | 'cli' | 'servers' | 'equation-reader' | 'ocr-tool' | 'provider' | 'api-key' | 'zotero' | 'reference-files'; id: string }
type Tone = 'ok' | 'no' | 'warn'

// A tile (mockup `.conn`): the name with its status pill, then one line on what it is. Green only when it can be used.
function Tile({ name, desc, tone, status, active, onClick }: { name: string; desc: string; tone: Tone; status: string; active: boolean; onClick: () => void }) {
  return <button type="button" className={`conn ${active ? 'on' : ''}`} onClick={onClick}>
    <b><span className="conn-name">{name}</span><span className={`st ${tone}`}>{status}</span></b>
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
function KeyField({ env, entry, keychain, label, service, removeEffect, onSaved }: {
  env: string; entry: KeyEntry | undefined; keychain: Keychain; label: string; service: string; removeEffect: string; onSaved: () => void
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [asking, setAsking] = useState(false)
  const toast = useToast()
  if (!entry) return null
  const id = `key-${env}`
  if (entry.source === 'environment') return <p className="foot-note">{t('This key is set in the shell that started DEIXIS; change or remove it there.')}</p>
  const inDotenv = entry.source === 'dotenv'
  if (!entry.configured && !keychain.available) return <p className="foot-note">{t('No system keychain is available; set the key in .env.')}</p>
  const where = inDotenv ? t('stored in .env') : t('stored in {keychain}', { keychain: keychain.name ?? t('the system keychain') })
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
      ? t('The key was not saved.') + ' ' + serviceErrorSentence({ kind: e.details?.kind, service, resetAt: e.details?.reset_at, effect: 'settings' })
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
      <input id={id} className="field" type="password" autoComplete="off" spellCheck={false} value={value} disabled={busy}
        placeholder={entry.configured ? `•••••••••••• ${where}` : t('Paste your key')} onChange={e => { setValue(e.target.value); setFormError('') }} />
    </label>
    <p className="foot-note">{inDotenv ? t('Stored in .env, never in research files or exports.') : t('Stored in {keychain}, never in research files or exports.', { keychain: keychain.name ?? t('the system keychain') })}
      {entry.testable && ` ${t('A new key is tested with one short request before it is saved.')}`}</p>
    {formError && <p className="key-form-error" role="alert">{formError}</p>}
    <div className="acts">
      {primary && <button type="submit" className="btn-pri" disabled={busy}>{busy ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t(busy ? (typed ? (entry.testable ? 'Testing and saving…' : 'Saving…') : 'Testing…') : primary)}</button>}
      {entry.configured && !asking && <button type="button" className="ghost" disabled={busy} onClick={() => setAsking(true)}>{t('Remove key')}</button>}
    </div>
    {asking && <RemoveNotice busy={busy} onRemove={remove} onKeep={() => setAsking(false)}
      text={t('Remove the key for {name}?', { name: service }) + ' ' + (inDotenv ? t('Its line is deleted from .env.') + ' ' : '') + removeEffect} />}
  </form>
}

// The contact email (F15): sent as `mailto` with OpenAlex and Crossref requests; the setting wins over DEIXIS_CONTACT_EMAIL.
function ContactEmailField() {
  const [stored, setStored] = useState<ContactEmailSetting | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const toast = useToast()
  useEffect(() => {
    let live = true
    shellApi.contactEmail().then(value => { if (live) { setStored(value); setDraft(value.email ?? '') } }, (e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [])
  const save = () => {
    setBusy(true); setError('')
    shellApi.saveContactEmail(draft.trim() || null).then(value => {
      setStored(value); setDraft(value.email ?? '')
      toast('success', t(value.email ? 'Contact email saved.' : 'Contact email removed.'))
    }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  const changed = stored !== null && draft.trim() !== (stored.email ?? '')
  return <form className="contact-field" onSubmit={e => { e.preventDefault(); if (changed) save() }}>
    <label className="lbl" htmlFor="contact-email">{t('Contact email (sent as mailto)')}
      <input id="contact-email" className="field" type="email" autoComplete="email" value={draft} disabled={stored === null || busy} placeholder="you@university.edu"
        onChange={e => { setDraft(e.target.value); setError('') }} />
    </label>
    {stored && !stored.email && stored.environment_set && <p className="foot-note">{t('While this field is empty, DEIXIS_CONTACT_EMAIL from the environment is sent.')}</p>}
    {error && <p className="key-form-error" role="alert">{error}</p>}
    <div className="acts"><button type="submit" className="ghost" disabled={busy || !changed}>{t(busy ? 'Saving…' : 'Save')}</button></div>
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
    {tool.kind === 'cli' && tool.role === 'detected' && <p className="local-tool-note">{t('Detected only: DEIXIS found (or did not find) this tool, but it does not run research steps and no step is sent to it.')}</p>}
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
    {tool.kind === 'app' && <p className="local-tool-note">{t(tool.web_configured ? 'zotero.org: ZOTERO_API_KEY and ZOTERO_LIBRARY_ID are set.' : 'zotero.org: set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in .env to import from the web library.')}</p>}
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

// The local OCR tool (D51): detected, not installed by DEIXIS.
function OcrToolDetails({ tool }: { tool: OcrTool }) {
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
export function ConnectionsTab({ dark, access, onConnections }: { dark: boolean; access: ReactNode; onConnections?: (connections: Connections) => void }) {
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
      setChecked(old => ({ ...old, [key]: Date.now() })); setCheckFailed(drop)
    }, (e: Error) => { setChecked(drop); setCheckFailed(old => ({ ...old, [key]: e.message })) })
      .finally(() => setChecking(current => current === key ? null : current))
  }
  const refreshModel = (id: string) => api.modelConnection(id, true).then(result => {
    setData(current => current ? { ...current, models: { ...current.models, [id]: result } } : current)
  }).catch((e: Error) => { toast('error', t('Check failed: {message}', { message: e.message })); throw e })
  const show = (item: Selected) => { setSelected(item); setOpen(true); setSignIn(null) }
  const isActive = (kind: Selected['kind'], id: string) => open && !gone && selected?.kind === kind && selected.id === id
  const check = (label: string, value: string) => <div className="legacy-check" key={label}><span>{label}</span><strong>{value}</strong></div>

  const modelEntries = Object.entries(data?.models ?? {})
  const plannedModels = modelEntries.filter(([, m]) => isPlannedModel(m.reason))
  const cloudModels = modelEntries.filter(([id, m]) => !isPlannedModel(m.reason) && !ACCOUNT_TOOLS[id])
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
  const modelDesc = (id: string) => id === 'gemini' ? t('API key · models and semantic search') : compatConnectionKeys[id] ? t('API key · not yet verified against the live API') : t('API key')
  const tile = (key: string, kind: Selected['kind'], id: string, name: string, desc: string, [tone, status]: [Tone, string]) =>
    <Tile key={key} name={name} desc={desc} tone={tone} status={status} active={isActive(kind, id)} onClick={() => show({ kind, id })} />

  // Semantic search rows (plan ST5): the mockup's five, one "Local model server" for Ollama and LM Studio. A row that
  // cannot be chosen says what it needs, from the options' own state. A choice is saved at once; choosing the row that
  // is only the default (nothing saved yet) saves it too.
  const option = (p: SemanticSearchProvider) => semantic?.options.find(o => o.provider === p)
  const serverOptions = SERVER_IDS.map(id => option(id as SemanticSearchProvider)).filter((o): o is SemanticSearchOption => !!o)
  const serverChoices = serverOptions.filter(o => o.available).flatMap(o => o.models.map(m => ({ provider: o.provider, model: m, label: `${o.provider === 'ollama' ? 'Ollama' : 'LM Studio'} · ${m}` })))
  const chosen = pending ?? (semantic ? { provider: semantic.provider, model: semantic.model } : null)
  const saving = pending !== null
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
  const semanticRows: { id: string; label: string; desc: string; providers: SemanticSearchProvider[]; body?: ReactNode }[] = [
    { id: 'builtin', providers: ['builtin'], label: t('This computer · built-in'),
      desc: t('A small embedding model that runs on this computer. No key; for semantic search, no text leaves the computer.'),
      body: <>
        <p className="local-tool-note">{t('English only: a research whose question is not in English needs one English sentence. The model you chose for the research steps still receives what it receives today.')}</p>
        <p className="local-tool-note">{t('Measured on one Apple M1 Pro: 1,369 records took 51 seconds, 6,696 records about 4 minutes. Other computers were not measured.')}</p>
        {builtin && <BuiltinEmbeddingPanel builtin={builtin} dark={dark} onChanged={async () => { await loadBuiltin(); await loadSemantic() }} />}
      </> },
    { id: 'openai', providers: ['openai'], label: t('OpenAI embeddings'),
      desc: t('{model} · sends titles, abstracts and passage text to OpenAI', { model: option('openai')?.models[0] ?? 'text-embedding-3-small' }) },
    { id: 'gemini', providers: ['gemini'], label: t('Gemini embeddings'),
      desc: t('{model} · sends titles, abstracts and passage text to Google', { model: option('gemini')?.models[0] ?? 'gemini-embedding' }),
      body: <>
        <p className="local-tool-note">{t('Reads the question in any language. Needs a Google AI Studio key; a free key works.')}</p>
        {!option('gemini')?.available && <GeminiKeyPath />}
      </> },
    { id: 'server', providers: ['ollama', 'lm_studio'], label: t('Local model server'), desc: t('An embedding model on Ollama or LM Studio') },
    { id: 'off', providers: ['off'], label: t('Off'), desc: t('Keyword search only; sources get no similarity score.') },
  ]
  const privacy = !semantic ? null : semantic.provider === 'off' ? t('Sources get no similarity score; passages are ranked by keyword match only. No text is sent anywhere.')
    : semantic.provider === 'gemini' ? t('Passage text is sent to Google. If your key is on Google’s free tier, Google may use the text you send to improve its products. DEIXIS cannot tell which tier your key is on.')
    : semantic.provider === 'openai' ? t('Passage text is sent to {service}.', { service: 'OpenAI' })
    : semantic.provider === 'builtin' ? t('For semantic search, no text leaves the computer.') : t('Passage text stays on this computer.')

  // ---- the connection sheet ----
  const sel = selected
  const accountId = sel?.kind === 'account' ? sel.id : null
  const model = sel?.kind === 'model' ? data?.models[sel.id] : accountId ? data?.models[accountId] : undefined
  const provider = sel?.kind === 'provider' ? data?.providers.find(p => p.id === sel.id) : undefined
  const cliTool = sel?.kind === 'cli' ? toolOf(sel.id) : accountId ? toolOf(ACCOUNT_TOOLS[accountId].tool) : undefined
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
  const checkedLine = (key: string) => checkFailed[key] ? <span className="warn-t check-failed">{t('Could not check: {message}', { message: checkFailed[key] })}</span>
    : checked[key] ? <span>{t('checked {time}', { time: clock(checked[key]) })}</span> : null
  const dmeta = (key: string, [tone, status]: [Tone, string], extra?: ReactNode) =>
    <p className="dmeta">{checking === key ? <span><span className="spin" aria-hidden /> {t('Checking…')}</span> : <span className={tone === 'ok' ? 'ok-t' : tone === 'warn' ? 'warn-t' : ''}>{status}</span>}{extra}{checking !== key && checkedLine(key)}</p>
  const checkButton = (key: string, label: string, run: () => Promise<unknown>, disabled = false) =>
    <button type="button" className="btn-pri" disabled={disabled || checking !== null} onClick={() => runCheck(key, run)}>{checking === key ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t(label)}</button>
  // The Codex home this backend uses (DEIXIS_CODEX_HOME or the data folder's), single-quoted for a POSIX shell.
  const codexLogin = data?.codex_home ? `CODEX_HOME='${data.codex_home.replaceAll("'", "'\\''")}' codex login` : null
  const signInCommand = accountId === 'codex' ? codexLogin : accountId === 'claude' ? 'claude' : null
  const copy = (text: string) => { writeClipboard(text).then(() => toast('success', t('Command copied.')), () => toast('error', t('Could not copy; select the command and copy it.'))) }

  const keyedSheet = (env: string, service: string, effect: string) => credentials && <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain}
    label={t('API key')} service={service} removeEffect={effect} onSaved={reloadAfterKeyChange} />

  let body: ReactNode = null
  if (sel?.kind === 'account' && accountId) {
    const key = `account:${accountId}`
    body = <>
      {dmeta(key, accountStatus(accountId))}
      <p className="foot-note is-ink">{t(accountId === 'codex'
        ? 'Uses the account you sign in with through Codex CLI, kept in the DEIXIS Codex home. DEIXIS stores no password of its own.'
        : 'Uses the account you are signed in with in Claude Code. DEIXIS keeps no password or token of its own.')}</p>
      <div className="acts">
        {checkButton(key, 'Test the connection', () => refreshModel(accountId), !model)}
        {signInCommand && <button type="button" className="ghost" aria-expanded={signIn === accountId} onClick={() => setSignIn(signIn === accountId ? null : accountId)}>{t('Sign in again')}</button>}
      </div>
      {signIn === accountId && signInCommand && <div className="signin-cmd">
        <p className="foot-note">{t(accountId === 'codex' ? 'Run this in a terminal, then test the connection:' : 'Run this in a terminal, type /login, then test the connection:')}</p>
        <div className="cmd-row"><code className="field mono">{signInCommand}</code><button type="button" className="ghost" onClick={() => copy(signInCommand)}><Copy aria-hidden />{t('Copy')}</button></div>
      </div>}
      {model && !model.ready && <p className="foot-note">{healthReasonText(model)}</p>}
      {model && accountId === 'codex' && <>
        <p className="foot-note">{t('DEIXIS runs Codex in its own Codex home with tools, connectors, skills and instruction files disabled, and starts a new session for every step.')}</p>
        <div className="connection-checks">
          {check('CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
          {check(t('Signed in (DEIXIS Codex home)'), model.signed_in ? t('yes · {plan}', { plan: model.plan_type ?? model.account_type ?? '' }) : t('no'))}
          {check(t('Instruction files loaded'), model.isolation ? String(model.isolation.instruction_sources) : t('not checked'))}
          {check(t('MCP servers with tools'), model.isolation ? (model.isolation.live_mcp_servers.join(', ') || t('none')) : t('not checked'))}
        </div>
      </>}
      {model && accountId === 'claude' && <>
        <p className="foot-note">{t('DEIXIS runs Claude Code through the official Agent SDK with tools, MCP servers, skills and instruction files disabled, and starts a new non-persistent session for every step.')}</p>
        <div className="connection-checks">
          {check('CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
          {check(t('Signed in to Claude Code'), model.signed_in ? t('yes · {plan}', { plan: model.plan_type ?? model.account_type ?? '' }) : t('no'))}
          {check(t('Instruction files loaded'), model.isolation ? String(model.isolation.instruction_sources) : t('not checked'))}
          {check(t('MCP servers with tools'), model.isolation ? (model.isolation.live_mcp_servers.join(', ') || t('none')) : t('not checked'))}
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
      {dmeta(key, modelStatus(model))}
      {!model.ready && model.key_configured !== false && <p className="foot-note">{healthReasonText(model)}</p>}
      <p className="foot-note is-ink">{t('Passages are sent to the provider you choose. Once a key is saved it is never shown again; it can only be replaced or removed.')}</p>
      {env && keyedSheet(env, modelNames[sel.id] ?? sel.id, t('This connection stops working until a new key is added.'))}
      {sel.id === 'gemini' && <>
        <p className="foot-note">{t('DEIXIS calls the Gemini API directly with GEMINI_API_KEY, with no tools, instruction files or CLI agent prompt, and one new request per step. The Gemini CLI is only detected; it does not run steps.')}</p>
        <div className="connection-checks">
          {check(t('API key (GEMINI_API_KEY)'), model.key_configured ? t('set') : t('not set'))}
          {check('Gemini CLI', model.installed ? model.cli_version ?? t('installed') : t('not found'))}
          {check(t('Semantic passage search'), model.key_configured ? t('on · passage text is sent to Google') : t('off'))}
        </div>
      </>}
      {sel.id === 'deepseek' && <>
        <p className="foot-note">{t('DEIXIS calls the DeepSeek API directly with DEEPSEEK_API_KEY, with no tools or instruction files and one new request per step.')}</p>
        <div className="connection-checks">{check(t('API key (DEEPSEEK_API_KEY)'), model.key_configured ? t('set') : t('not set'))}</div>
      </>}
      {compatConnectionKeys[sel.id] && <>
        <p className="foot-note">{t('DEIXIS calls the {name} API directly through its OpenAI-compatible endpoint with {env}, with no tools or instruction files and one new request per step. Not yet verified against the live API.', { name: modelNames[sel.id] ?? sel.id, env: compatConnectionKeys[sel.id] })}</p>
        <div className="connection-checks">{check(t('API key ({env})', { env: compatConnectionKeys[sel.id] }), model.key_configured ? t('set') : t('not set'))}</div>
      </>}
      <div className="acts">{checkButton(key, 'Check again', () => refreshModel(sel.id))}</div>
      <ModelCatalogue model={model} />
    </>
  } else if (sel?.kind === 'api-key') {
    body = <>
      {dmeta('api-key', openaiKey?.configured ? ['ok', t('Key configured')] : ['no', t('Not set up')])}
      <p className="foot-note is-ink">{t('Used for semantic search only, when OpenAI embeddings are chosen. Once a key is saved it is never shown again; it can only be replaced or removed.')}</p>
      {keyedSheet('OPENAI_API_KEY', 'OpenAI', t('Semantic search with OpenAI stops until a new key is added.'))}
    </>
  } else if (sel?.kind === 'provider' && provider) {
    const env = providerKeyEnv[provider.id]
    const [tone, status] = providerStatus(provider.access_mode)
    body = <>
      {dmeta(`provider:${provider.id}`, [tone, status], provider.id === 'openalex' && provider.access_mode !== null
        ? <span className={provider.access_mode === 'api_key' ? '' : 'warn-t'}>{t(provider.access_mode === 'api_key' ? 'own key' : 'keyless')}</span> : null)}
      <p className="foot-note is-ink">{provider.id === 'openalex'
        ? t('Works without a key. A free key from openalex.org gives DEIXIS its own daily budget. When the budget runs out, OpenAlex requests wait until it resets.')
        : !env ? (MAILTO_PROVIDERS.has(provider.id) ? t('No key needed. DEIXIS adds your contact email to its requests (mailto), as the service asks.') : t('No key needed.'))
        : provider.note}</p>
      {env && credentials && <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain} service={providerNames[provider.id] ?? provider.id}
        label={t(provider.id === 'openalex' ? 'API key (optional, free from openalex.org)' : 'API key')}
        removeEffect={t('Requests that need this key stop until you add one again.')} onSaved={reloadAfterKeyChange} />}
      {MAILTO_PROVIDERS.has(provider.id) && <ContactEmailField />}
      <div className="connection-checks">{check(t('Used for'), providerUse[provider.id] ? t(providerUse[provider.id]) : providerRole(provider.role))}{check(t('Access mode'), provider.access_mode ? t(provider.access_mode) : t('none'))}</div>
      {(env || provider.id === 'openalex') && <p className="foot-note">{t('Access and quota are recorded per request; not verified in advance.')}</p>}
      {!env && provider.id !== 'openalex' && <p className="foot-note">{provider.note}</p>}
    </>
  } else if (sel?.kind === 'cli' && cliTool) {
    body = <LocalToolDetails key={cliTool.id} tool={cliTool} dark={dark} onChanged={reloadTools} />
  } else if (sel?.kind === 'servers') {
    body = <>
      {dmeta('servers', serversStatus())}
      <p className="foot-note is-ink">{t('Runs on this computer. Semantic search can use an embedding model from Ollama or LM Studio; local models do not run research steps in this version.')}</p>
      {servers.map(server => <section key={server.id} className="server-block" aria-label={server.name || localToolNames[server.id]}>
        <h3>{server.name || localToolNames[server.id]}</h3>
        {server.endpoint && <div className="lbl">{t('Server address')}<code className="field mono">{server.endpoint}</code></div>}
        <LocalToolDetails tool={server} dark={dark} onChanged={reloadTools} refresh={false} />
      </section>)}
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
      <p className="foot-note is-ink">{t('Collections are imported read-only from the home composer’s Add sources menu or a research’s Sources panel.')}</p>
      <div className="acts">{checkButton('zotero', 'Find it on this computer', () => loadTools(true, true))}</div>
      {zotero && <LocalToolDetails tool={zotero} dark={dark} onChanged={reloadTools} refresh={false} />}
    </>
  } else if (sel?.kind === 'reference-files') {
    body = <>
      <p className="foot-note is-ink">{t('Imports a .bib or .ris file into the Library. An entry whose DOI OpenAlex or Crossref confirms is stored as that provider’s record; any other entry is kept as your own record, marked as not confirmed.')}</p>
      <ReferenceFileImport />
    </>
  }

  return <>
    {error && <Notice tone="error">{error}</Notice>}

    <div className="cloud-models">
    <h2>{t('Cloud models')}</h2>
    <p className="foot-note">{t('Passages are sent to the provider you choose. Once a key is saved it is never shown again; it can only be replaced or removed.')}</p>
    <div className="grid3" data-group="cloud">
      {cloudModels.map(([id, m]) => tile(id, 'model', id, modelNames[id] ?? id, modelDesc(id), modelStatus(m)))}
      {tile('openai', 'api-key', 'OPENAI_API_KEY', t('OpenAI API'), t('API key · semantic search only'), !credentials ? loading : openaiKey?.configured ? ['ok', t('Key configured')] : ['no', t('Not set up')])}
    </div>
    {plannedModels.length > 0 && <details className="planned-connections"><summary><ChevronRight size={14} aria-hidden />{t('Planned model connections · {n}', { n: plannedModels.length })}</summary>
      <div className="grid3">{plannedModels.map(([id]) => tile(id, 'model', id, modelNames[id] ?? id, t('Not available in this version'), ['no', t('Planned')]))}</div>
    </details>}
    </div>

    <h2 id="on-this-computer" tabIndex={-1}>{t('On this computer')}</h2>
    {toolsError && <Notice tone="error">{toolsError}</Notice>}
    <div className="grid3" data-group="computer">
      {tile('codex', 'account', 'codex', 'Codex CLI', t('Account sign-in'), accountStatus('codex'))}
      {tile('claude', 'account', 'claude', 'Claude Code', t('Account sign-in'), accountStatus('claude'))}
      {tile('ocr', 'ocr-tool', 'tesseract', t('OCR (Tesseract)'), t('Scanned PDFs'), ocrStatus())}
      {tile('servers', 'servers', 'servers', t('Local model servers'), t('Ollama or LM Studio · no account'), serversStatus())}
      {tile('marker', 'equation-reader', 'marker', t('Equation reader (Marker)'), t('Reads equations as LaTeX'), readerStatus())}
    </div>
    {(otherCli.length > 0 || machine) && <div className="computer-more">
      {machine && (machine.chip || machine.memory_gb != null || machine.disk_free_gb != null) && <p className="foot-note local-tool-machine">
        {machine.chip && <span>{t('This computer: {chip}', { chip: machine.chip })}</span>}
        {machine.memory_gb != null && <span>{t('Memory: {gb} GB', { gb: machine.memory_gb })}</span>}
        {machine.disk_free_gb != null && <span>{t('Free disk: {gb} GB', { gb: machine.disk_free_gb })}</span>}
      </p>}
      {otherCli.length > 0 && <details className="planned-connections"><summary><ChevronRight size={14} aria-hidden />{t('Other command-line tools · {n}', { n: otherCli.length })}</summary>
        <p className="foot-note">{t('Only Claude Code and Codex CLI run research steps. The other tools are detected only: finding one here does not mean DEIXIS supports it.')}</p>
        <div className="grid3">{otherCli.map(tool => tile(tool.id, 'cli', tool.id, tool.name || localToolNames[tool.id] || tool.id, t('Detected only'), ['no', t(tool.job?.status === 'running' ? 'Installing…' : tool.installed ? 'Installed' : 'Not installed')]))}</div>
      </details>}
    </div>}

    <h2>{t('Semantic search')}</h2>
    <p className="foot-note">{t('Ranks search results by meaning, not only by shared words. Changing the provider embeds passages again; earlier vectors are kept.')}</p>
    {semError && <Notice tone="error">{semError}</Notice>}
    <div className="rows opts semantic-choices" role="radiogroup" aria-label={t('Semantic search provider')} aria-busy={saving || undefined}>
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
            <span>{row.label}<small>{row.desc}</small></span>
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
    {privacy && <p className="foot-note semantic-privacy">{privacy}</p>}

    {access}

    <h2>{t('Scholarly sources')}</h2>
    <div className="grid3" data-group="sources">{providers.map(p => tile(p.id, 'provider', p.id, providerNames[p.id] ?? p.id, providerUse[p.id] ? t(providerUse[p.id]) : providerRole(p.role), providerStatus(p.access_mode)))}</div>
    <p className="foot-note sources-note">{t('Every provider with the access it needs is enabled for new researches. Access and remaining quota are recorded with each request rather than guaranteed in advance.')}</p>

    <h2>{t('Reference managers')}</h2>
    <div className="grid3" data-group="references">
      {tile('zotero', 'zotero', 'zotero', 'Zotero', t('Read-only collections'), zoteroStatus())}
      {tile('reference-files', 'reference-files', 'files', t('BibTeX / RIS files'), t('Import a .bib or .ris file'), ['ok', t('Available')])}
    </div>

    <Sheet open={open && !gone} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet connection-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader><SheetTitle><Link size={16} aria-hidden /><span>{name}</span></SheetTitle><SheetDescription className="sr-only">{t('{name} details', { name })}</SheetDescription></SheetHeader>
        <div className="connection-body mk pad detail">{body}</div>
      </SheetContent>
    </Sheet>
  </>
}
