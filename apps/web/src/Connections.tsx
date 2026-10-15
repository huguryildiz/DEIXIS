import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Ban, BookOpenText, ChevronRight, CircleCheck, Copy, Cpu, FileText, HardDrive, MemoryStick, LoaderCircle, Plus, RefreshCw, RotateCw, Save, ScanText, Server, Sigma, TriangleAlert, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ConfirmDialog } from './ConfirmDialog'
import { DataLocationCard } from './DataLocation'
import { api, ApiError, libraryImportsApi, type AccountSignIn, type BuiltinEmbedding, type Connections, type Credentials, type KeyEntry, type Keychain, type EquationReader, type LocalTool, type OcrTool, type PdfReader, type ToolUpdate, type LocalTools, type ProviderTest, type ModelHealth, type ReferenceImport, type SemanticSearch, type SemanticSearchOption, type SemanticSearchProvider } from './api'
import { useToast } from './Toast'
import { ocrLanguagesText } from './ocr'
import { t, uiLocale } from './i18n'
import { serviceErrorSentence, healthReasonText, localToolIcon, localToolNames, providerRole, reasoningLabel } from './labels'
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
// Where each key is obtained and the shortest route to it (checked on the providers' own pages, 15 Oct 2026).
const OPENALEX_SIGNUP = { url: 'https://openalex.org/settings/api', steps: 'Create a free account at openalex.org, then copy the key from Settings → API.' }
const providerKeySignup: Record<string, { url: string; steps: string }> = {
  openalex: OPENALEX_SIGNUP,
  biorxiv: { url: OPENALEX_SIGNUP.url, steps: 'bioRxiv uses the OpenAlex key. Create a free account at openalex.org, then copy the key from Settings → API.' },
  semantic_scholar: { url: 'https://www.semanticscholar.org/product/api#api-key-form', steps: 'Fill in the request form. The key arrives by email, which can take a few days.' },
  scopus: { url: 'https://dev.elsevier.com/apikey/manage', steps: 'Sign in to the Elsevier Developer Portal and create a key. Scopus answers only through an institutional subscription, so the key works from your institution’s network.' },
  pubmed: { url: 'https://account.ncbi.nlm.nih.gov/settings/', steps: 'Sign in to an NCBI account, then open Account settings → API Key Management and choose Create.' },
  ieee_xplore: { url: 'https://developer.ieee.org/getting_started', steps: 'Register a developer account, then request a key for an application. Keys are sent during US business hours.' },
  core: { url: 'https://core.ac.uk/services/api', steps: 'Choose Register on the CORE API page and fill in the form. The key arrives by email.' },
  serpapi: { url: 'https://serpapi.com/users/sign_up', steps: 'Sign up, then copy the key from the dashboard. The free plan allows 250 searches a month.' },
}
// Sources whose requests carry the contact email as `mailto` (openalex.py, crossref.py).
const MAILTO_PROVIDERS = new Set(['openalex', 'crossref'])
// The model connections that sign in with an account on this computer, and the command-line tool each one runs.
const ACCOUNT_TOOLS: Record<string, { tool: LocalTool['id']; name: string }> = { codex: { tool: 'codex', name: 'Codex CLI' }, claude: { tool: 'claude_code', name: 'Claude Code' }, copilot_cli: { tool: 'copilot_cli', name: 'GitHub Copilot CLI' }, gemini_cli: { tool: 'gemini_cli', name: 'Gemini CLI' } }
const SERVER_IDS = ['ollama', 'lm_studio']

// The Models tab (owner-approved connection mockup, 15 Oct 2026): one card per company, each with up to two ways to
// connect, an account sign-in and an API key, and each way keeps its own connection's state. Texts are English; the
// cards translate them. `site` fills the key sentence's {site}.
type KeyWay = { conn: string; env: string; label?: string; desc?: string; site: string; service?: string }
type Company = {
  id: string; name: string; maker: string; icon?: string; mono?: string
  account?: { conn: string; label: string; desc: string }
  soon?: string  // the account way that is not built yet: its label
  key: KeyWay
  keyFirst?: boolean  // the key is the recommended way (Gemini)
  intro?: string
  onlyWhenSet?: boolean  // an older connection, listed only while its key is saved
}
const PAY_AS_YOU_GO = 'Pay as you go. Get the key at {site}.'
const MAIN_COMPANIES: Company[] = [
  { id: 'claude', name: 'Claude', maker: 'Anthropic', icon: 'claude',
    account: { conn: 'claude', label: 'With your Claude account', desc: 'If you have a Claude Pro or Max subscription. No extra charge; your plan’s usage limit applies.' },
    key: { conn: 'anthropic', env: 'ANTHROPIC_API_KEY', site: 'console.anthropic.com', service: 'Anthropic' } },
  { id: 'chatgpt', name: 'ChatGPT', maker: 'OpenAI', icon: 'openai',
    account: { conn: 'codex', label: 'With your ChatGPT account', desc: 'If you have a ChatGPT Plus, Pro or Business subscription. No extra charge.' },
    key: { conn: 'openai', env: 'OPENAI_API_KEY', site: 'platform.openai.com', service: 'OpenAI', desc: 'Pay as you go. Get the key at {site}. The same key can also be used for semantic search.' } },
  { id: 'gemini', name: 'Gemini', maker: 'Google', icon: 'gemini', keyFirst: true,
    intro: 'Either way is enough. Google recommends an API key for apps that run Gemini in the background.',
    account: { conn: 'gemini_cli', label: 'With your Google account', desc: 'A free Google account is enough; there is a daily usage limit.' },
    key: { conn: 'gemini', env: 'GEMINI_API_KEY', site: 'aistudio.google.com', desc: 'Get the key at {site}. The same key can also be used for semantic search.' } },
  { id: 'copilot', name: 'GitHub Copilot', maker: 'GitHub', icon: 'copilot',
    account: { conn: 'copilot_cli', label: 'With your GitHub account', desc: 'If you have a Copilot subscription. Free for students and teachers.' },
    key: { conn: 'copilot', env: 'GITHUB_TOKEN', site: 'github.com/settings/tokens', service: 'GitHub Models', label: 'With a GitHub Models token', desc: 'Create a token with the “models” permission at {site}.' } },
  { id: 'grok', name: 'Grok', maker: 'xAI', icon: 'grok', soon: 'With your SuperGrok account', key: { conn: 'grok', env: 'XAI_API_KEY', site: 'console.x.ai', service: 'xAI' } },
  { id: 'mistral', name: 'Mistral', maker: 'Mistral AI', icon: 'mistral', soon: 'With your Mistral account', key: { conn: 'mistral', env: 'MISTRAL_API_KEY', site: 'console.mistral.ai' } },
]
const META_SITE = 'the Meta Model API (US only for now)'
const OTHER_COMPANIES: Company[] = [
  { id: 'openrouter', name: 'OpenRouter', maker: 'One key, many models', mono: 'OR', key: { conn: 'openrouter', env: 'OPENROUTER_API_KEY', site: 'openrouter.ai/keys' } },
  { id: 'muse', name: 'Muse', maker: 'Meta', icon: 'muse_spark', key: { conn: 'muse_spark', env: 'MODEL_API_KEY', site: META_SITE } },
  { id: 'mimo', name: 'MiMo', maker: 'Xiaomi', mono: 'Xi', key: { conn: 'mimo', env: 'MIMO_API_KEY', site: 'the Xiaomi MiMo API platform' } },
  { id: 'qwen', name: 'Qwen', maker: 'Alibaba', icon: 'qwen', key: { conn: 'qwen', env: 'DASHSCOPE_API_KEY', site: 'Alibaba Cloud Model Studio' } },
  { id: 'glm', name: 'GLM', maker: 'Z.ai', icon: 'glm', key: { conn: 'glm', env: 'ZAI_API_KEY', site: 'z.ai' } },
  { id: 'deepseek', name: 'DeepSeek', maker: 'DeepSeek', icon: 'deepseek', key: { conn: 'deepseek', env: 'DEEPSEEK_API_KEY', site: 'platform.deepseek.com' } },
  { id: 'kimi', name: 'Kimi', maker: 'Moonshot AI', icon: 'kimi', onlyWhenSet: true, key: { conn: 'kimi', env: 'MOONSHOT_API_KEY', site: 'platform.moonshot.ai' } },
  { id: 'muse_glimmer', name: 'Muse Glimmer', maker: 'Meta', icon: 'muse_glimmer', onlyWhenSet: true, key: { conn: 'muse_glimmer', env: 'MODEL_API_KEY', site: META_SITE } },
]
const COMPANIES = [...MAIN_COMPANIES, ...OTHER_COMPANIES]
// Models people have run on a local server; suggestions to try, not models DEIXIS has measured.
const LOCAL_TRY = 'Models to try: gpt-oss-20b (at least 24 GB of memory), Qwen3.5-35B-A3B, Gemma 4 31B, GLM-4.7-Flash (at least 32 GB each). Small models can struggle with long papers.'

// A company's mark: its brand icon in the tinted square, or two letters where the app has no icon for it.
const companyMark = (icon: string | undefined, mono: string | undefined, glyph?: ReactNode) =>
  <span className="co-mark" aria-hidden="true">{glyph ?? (icon ? <ConnectionIcon id={icon} /> : mono)}</span>

// A card (mockup `.card`): the mark, name and maker, the status pill, then one line on how it is connected. Green only
// when its connection says it is usable.
function CompanyCard({ mark, name, maker, via, ready, status, active, compact = false, onClick }: {
  mark: ReactNode; name: string; maker: string; via?: string; ready: boolean; status: string; active: boolean; compact?: boolean; onClick: () => void
}) {
  return <button type="button" className={`co-card ${compact ? 'is-compact' : ''} ${active ? 'on' : ''}`} onClick={onClick}>
    <span className="co-head">{mark}<span className="co-name"><b>{name}</b><small>{maker}</small></span><span className={`st ${ready ? 'ok' : 'no'}`}>{status}</span></span>
    {via && <span className="co-via">{via}</span>}
  </button>
}
const formatBytes = (bytes: number) => bytes / 1e9 >= 1 ? t('{gb} GB', { gb: (bytes / 1e9).toFixed(1) }) : t('{mb} MB', { mb: Math.round(bytes / 1e6) })
const clock = (iso: string | number) => new Date(iso).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })

// Settings icons, drawn in black and white (Settings.css): brand marks where connectionIcons.tsx has one, a plain glyph otherwise.
const glyph = (icon: ReactNode) => <span className="connection-icon" aria-hidden="true">{icon}</span>
const GLYPHS: Record<string, ReactNode> = {
  ocr: glyph(<ScanText strokeWidth={1.8} />), marker: glyph(<Sigma strokeWidth={1.8} />), pymupdf: glyph(<BookOpenText strokeWidth={1.8} />), servers: glyph(<Server strokeWidth={1.8} />),
  server: glyph(<Server strokeWidth={1.8} />), 'reference-files': glyph(<FileText strokeWidth={1.8} />), off: glyph(<Ban strokeWidth={1.8} />),
}
const settingsIcon = (key: string) => GLYPHS[key] ?? <ConnectionIcon id={localToolIcon(key)} />

type Selected = { kind: 'company' | 'local' | 'equation-reader' | 'ocr-tool' | 'pdf-reader' | 'provider' | 'zotero' | 'reference-files'; id: string }
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
function KeyField({ env, entry, keychain, label, service, removeEffect, onSaved, plain = false, note = true }: {
  env: string; entry: KeyEntry | undefined; keychain: Keychain; label: string; service: string; removeEffect: string; onSaved: () => void
  plain?: boolean  // an identifier, not a secret: typed in the open and named as an ID
  note?: boolean  // false when a sibling field already says where keys are stored
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [asking, setAsking] = useState(false)
  const toast = useToast()
  if (!entry) return null
  const id = `key-${env}`
  // A key saved here replaces one from the shell; removing it brings the shell key back.
  const fromShell = entry.source === 'environment'
  if (fromShell && !keychain.available) return <p className="foot-note">{t('This key comes from the terminal that started DEIXIS; change or remove it there.')}</p>
  const inDotenv = entry.source === 'dotenv'
  if (!entry.configured && !keychain.available) return <p className="foot-note">{t('No system keychain is available.')}</p>
  const where = inDotenv ? '' : fromShell ? t('from the terminal that started DEIXIS') : t('stored in {keychain}', { keychain: keychain.name ?? t('the system keychain') })
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
    {note && <p className="foot-note">{fromShell && `${t('This key comes from the terminal that started DEIXIS. A key saved here replaces it.')} `}{inDotenv ? t('Never stored in research files or exports.') : t('Stored in {keychain}, never in research files or exports.', { keychain: keychain.name ?? t('the system keychain') })}
      {entry.testable && ` ${t('A new key is tested with one short request before it is saved.')}`}</p>}
    {formError && <Notice tone="error"><p>{formError}</p></Notice>}
    <div className="acts">
      {primary && <button type="submit" className="btn-pri" disabled={busy}>{busy ? <span className="spin" aria-hidden /> : typed ? <Save aria-hidden /> : <CircleCheck aria-hidden />}{t(busy ? (typed ? (entry.testable ? 'Testing and saving…' : 'Saving…') : 'Testing…') : primary)}</button>}
      {entry.configured && !fromShell && !asking && <button type="button" className="ghost" disabled={busy} onClick={() => setAsking(true)}>{t(plain ? 'Remove ID' : 'Remove key')}</button>}
    </div>
    {asking && <RemoveNotice busy={busy} onRemove={remove} onKeep={() => setAsking(false)}
      text={t(plain ? 'Remove the ID for {name}?' : 'Remove the key for {name}?', { name: service }) + ' ' + (entry.shell_fallback ? t('DEIXIS goes back to the key from the terminal that started it.') : removeEffect)} />}
  </form>
}

// Warnings are left out: brew prints them for unrelated taps, so they rarely explain a failed install.
function errorLines(output: string): string[] {
  return output.split('\n').map(line => line.trim()).filter(line => /\berror\b|fatal|npm err!|permission denied|could not|not found/i.test(line)).slice(0, 3)
}

function LocalToolDetails({ tool, dark, onChanged, refresh = true, chip = true }: { tool: LocalTool; dark: boolean; onChanged: () => Promise<void>; refresh?: boolean; chip?: boolean }) {
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
    {chip && <span className={`status-chip ${tool.installed ? '' : 'is-configured'}`}>{t(tool.installed ? 'Installed' : 'Not installed')}</span>}
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
      <p className="local-tool-note">{!tool.running ? t('Not answering. Open Zotero and close any dialog it shows, then turn on Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”.') : tool.local_api ? t('Local API on · {endpoint}', { endpoint: tool.endpoint ?? '' }) : t('Running, but its local API is off. Turn on Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”.')}</p>
    </>}
    {!tool.installed && (tool.install.available
      ? <>
        {!running && <div className="actions"><Button size="sm" onClick={() => setConfirmOpen(true)}>{t('Install')}</Button></div>}
        <ConfirmDialog open={confirmOpen} dark={dark} title={t('Install {name}?', { name })} description={t('DEIXIS installs it on this computer.')} confirmLabel={t('Install')} cancelLabel={t('Cancel')} busy={busy} onConfirm={install} onOpenChange={setConfirmOpen} />
      </>
      : <p className="local-tool-note">{tool.install.unavailable_reason}<br /><a href={tool.install.url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>)}
    {tool.job && <>
      {running
        ? <InstallProgress label={t('Installing…')} />
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
    {ready && !running && <ToolUpdateCheck tool="marker" />}
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

// An indeterminate bar: the installers report the step they are on, not a fraction.
function InstallProgress({ label }: { label: string }) {
  return <div className="install-progress" role="status">
    <span className="install-progress-label"><LoaderCircle size={14} className="chat-spin" aria-hidden />{label}</span>
    <div className="install-progress-bar" aria-hidden><span /></div>
  </div>
}

// The release check for a PDF tool, sent when its panel opens; it answers in one quiet line. Marker and PyMuPDF are
// pinned by DEIXIS, so a newer release arrives with a DEIXIS update. A failed check shows nothing.
function useToolUpdate(tool: ToolUpdate['tool'], key: unknown = null) {
  const [result, setResult] = useState<ToolUpdate | null>(null)
  useEffect(() => {
    let live = true
    api.toolUpdate(tool).then(r => { if (live) setResult(r) }, () => { if (live) setResult(null) })
    return () => { live = false }
  }, [tool, key])
  return result?.error || !result?.latest ? null : result
}

function ToolUpdateCheck({ tool }: { tool: 'marker' | 'pymupdf' }) {
  const result = useToolUpdate(tool)
  if (!result?.installed) return null
  const stale = result.tested && result.installed !== result.tested
  return <>
    <p className="local-tool-note" role="status">{result.update_available
      ? t('Version {latest} comes with the next DEIXIS update.', { latest: result.latest ?? '' })
      : t('Up to date.')}</p>
    {stale && <p className="local-tool-note">{t('The installed Marker is {installed}, not {tested}. Remove it and install it again to get the tested version.', { installed: result.installed, tested: result.tested ?? '' })}</p>}
  </>
}

// PyMuPDF reads the text layer of every PDF; it comes with DEIXIS, so there is nothing to install.
function PdfReaderDetails({ reader }: { reader: PdfReader }) {
  return <div className="local-tool-details-panel">
    <span className="status-chip">{t('Installed')}</span>
    <p className="local-tool-note">{t('PyMuPDF reads the text, page numbers and layout of every PDF you add or DEIXIS fetches. It comes with DEIXIS, runs on this computer, and no file leaves it.')}</p>
    <dl className="local-tool-facts">
      <dt>{t('Version')}</dt><dd>{reader.version}</dd>
      <dt>{t('MuPDF')}</dt><dd>{reader.mupdf_version}</dd>
      <dt>{t('License')}</dt><dd>AGPL-3.0</dd>
    </dl>
    <ToolUpdateCheck tool="pymupdf" />
  </div>
}

// The local OCR tool (D51). Install and Update run the one fixed Homebrew command on the server; the panel shows its step.
function OcrToolDetails({ tool, onChanged }: { tool: OcrTool; onChanged: () => Promise<unknown> }) {
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const job = tool.job
  const running = job?.status === 'running'
  const ready = tool.available && !tool.missing_languages.length
  const update = useToolUpdate('tesseract', tool.version)
  function install() {
    setBusy(true)
    api.installOcr().then(() => onChanged()).catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }
  const phase = { preparing: 'Preparing…', downloading: 'Downloading…', installing: 'Installing…' }[job?.phase ?? 'preparing']
  return <div className="local-tool-details-panel">
    <p className="local-tool-note">{t('Tesseract reads scanned PDF pages that have no selectable text when you choose Read with OCR on a source. It runs on this computer, no file leaves it, and the PDF is not changed.')}</p>
    <p className="local-tool-note">{t('Text read by OCR is labelled wherever it is quoted. In a test on four scanned articles, 0.2–1.5% of characters were misread and equations were unusable, so check numbers and equations against the page.')}</p>
    {tool.version && <dl className="local-tool-facts">
      <dt>{t('Version')}</dt><dd>{tool.version}{ready && update && !update.update_available && <span className="local-tool-uptodate"> · {t('up to date')}</span>}</dd>
      {tool.languages.length > 0 && <><dt>{t('Languages')}</dt><dd>{ocrLanguagesText(tool.languages)}</dd></>}
      {tool.missing_languages.length > 0 && <><dt>{t('Missing')}</dt><dd>{ocrLanguagesText(tool.missing_languages)}</dd></>}
    </dl>}
    {running
      ? <InstallProgress label={t(phase)} />
      : !ready
        ? (tool.can_install
          ? <div className="actions"><Button size="sm" onClick={install} disabled={busy}>{t('Install')}</Button></div>
          : <p className="local-tool-note">{t('Installing Tesseract needs Homebrew.')} <a href="https://brew.sh" target="_blank" rel="noopener noreferrer">brew.sh</a></p>)
        : update?.update_available && tool.can_install && <div className="tool-update-row">
          <span>{t('Version {latest} is available.', { latest: update.latest ?? '' })}</span>
          <Button size="sm" onClick={install} disabled={busy}>{t('Update')}</Button>
        </div>}
    {job?.status === 'failed' && <>
      <p className="local-tool-error">{t('Install failed.')}</p>
      {job.output && <details className="local-tool-details"><summary>{t('Show full output')}</summary><pre className="local-tool-output">{job.output}</pre></details>}
    </>}
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

// Turns the bare site addresses in a settings sentence (openalex.org, zotero.org/settings/keys) into links.
function linkify(text: string): ReactNode {
  return text.split(/(\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:org|com|uk|gov|ai)(?:\/[\w\/#?=.-]*[\w\/])?)/).map((part, i) => i % 2
    ? <a key={i} href={`https://${part}`} target="_blank" rel="noopener noreferrer">{part}</a> : part)
}

function GeminiKeyPath() {
  const [before, after] = t('Get a free key: sign in at {link}, create a key, paste it under Model connections → Gemini.').split('{link}')
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

// The sections of the Settings page that read connections: on the Models tab the company cards (Model connections,
// Other models, Local models), This computer, the page's Default models, Semantic search and Document reading; on the
// Sources tab the institutional access block given by the page, Scholarly sources and Reference managers; and the
// connection sheet every card and tile opens.
export function ConnectionsTab({ dark, access, defaults, onConnections, openProvider }: {
  dark: boolean; access: ReactNode; onConnections?: (connections: Connections) => void; openProvider?: string
  defaults?: ReactNode  // the page's Default models block, placed after the model connections
}) {
  const [data, setData] = useState<Connections | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Selected | null>(null)
  const [open, setOpen] = useState(false)
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [tools, setTools] = useState<LocalTools | null>(null)
  const [toolsError, setToolsError] = useState('')
  const [reader, setReader] = useState<EquationReader | null>(null)
  const [ocrTool, setOcrTool] = useState<OcrTool | null>(null)
  const [pdfReader, setPdfReader] = useState<PdfReader | null>(null)
  const [semantic, setSemantic] = useState<SemanticSearch | null>(null)
  const [semError, setSemError] = useState('')
  const [pending, setPending] = useState<{ provider: SemanticSearchProvider; model: string | null } | null>(null)
  const [builtin, setBuiltin] = useState<BuiltinEmbedding | null>(null)
  // What this sheet checked itself, and when the answer came: "checked HH:MM" belongs to that answer only.
  const [checking, setChecking] = useState<string | null>(null)
  const [checked, setChecked] = useState<Record<string, number>>({})
  const [checkFailed, setCheckFailed] = useState<Record<string, string>>({})
  // The sign-in DEIXIS started for a tool (D21); it is polled while the person finishes it in the terminal window that opened.
  const [signInRun, setSignInRun] = useState<{ tool: string; run: AccountSignIn } | null>(null)
  // The last answer to each keyless source's Test; shown only while its check's time is (the same check's answer).
  const [providerTests, setProviderTests] = useState<Record<string, ProviderTest>>({})
  const [showOthers, setShowOthers] = useState(false)
  // The local server address being typed (null: the saved one shows), and its save.
  const [serverDraft, setServerDraft] = useState<string | null>(null)
  const [serverBusy, setServerBusy] = useState(false)
  const [serverError, setServerError] = useState('')
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
    if (ocrTool?.job?.status !== 'running') return
    const timer = window.setInterval(() => { void loadOcr() }, 1500)
    return () => window.clearInterval(timer)
  }, [ocrTool, loadOcr])
  useEffect(() => { api.pdfReader().then(setPdfReader, (e: Error) => setToolsError(e.message)) }, [])
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
  const show = (item: Selected) => { setSelected(item); setOpen(true) }
  // A link to one provider's sheet (`#/settings/openalex`) opens it once the providers are read.
  const opened = useRef(false)
  useEffect(() => {
    if (!openProvider || opened.current || !data?.providers?.some(p => p.id === openProvider)) return
    opened.current = true
    setSelected({ kind: 'provider', id: openProvider }); setOpen(true)
  }, [openProvider, data])
  const isActive = (kind: Selected['kind'], id: string) => open && !gone && selected?.kind === kind && selected.id === id
  const check = (label: string, value: string) => <div className="legacy-check" key={label}><span>{label}</span><strong>{value}</strong></div>

  const toolOf = (id: string) => tools?.tools.find(tool => tool.id === id)
  const zotero = toolOf('zotero')
  const machine = tools?.machine
  const providers = [...(data?.providers ?? [])].sort((a, b) => {
    const rank = (id: string) => { const i = PROVIDER_ORDER.indexOf(id); return i < 0 ? PROVIDER_ORDER.length : i }
    return rank(a.id) - rank(b.id)
  })
  const keyEntry = (env: string) => credentials?.keys.find(k => k.env === env)

  // A sheet whose subject is no longer listed closes; one still loading stays.
  const gone = !!selected && (selected.kind === 'provider' ? !!data && !data.providers.some(p => p.id === selected.id)
    : selected.kind === 'zotero' ? !!tools && !tools.tools.some(tool => tool.id === selected.id)
    : selected.kind === 'company' ? !COMPANIES.some(c => c.id === selected.id)
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
  const ocrStatus = (): [Tone, string] => !ocrTool ? (toolsError ? unknown : loading)
    : !ocrTool.available ? ['no', t('Not installed')] : !ocrTool.missing_languages.length ? ['ok', t('Installed')]
    : ['warn', t(ocrTool.languages.join() === 'eng' ? 'English only' : 'Languages missing')]
  const pdfReaderStatus = (): [Tone, string] => pdfReader ? ['ok', t('Installed')] : toolsError ? unknown : loading
  const readerStatus = (): [Tone, string] => !reader ? (toolsError ? unknown : loading)
    : reader.job?.status === 'running' ? ['no', t('Installing…')] : reader.installed && reader.models_downloaded ? ['ok', t('Installed')] : ['no', t('Not installed')]
  const providerStatus = (mode: string | null): [Tone, string] => mode === 'api_key' ? ['ok', t('Key configured')] : mode === 'keyless' ? ['ok', t('No key needed')] : ['no', t('Not set up')]
  const zoteroStatus = (): [Tone, string] => !zotero ? (tools ? ['no', t('Not set up')] : toolsError ? unknown : loading)
    : zotero.running && zotero.local_api ? ['ok', t('Local API on')] : zotero.web_configured ? ['ok', t('zotero.org set')]
    : zotero.installed ? ['no', t(zotero.running ? 'Local API off' : 'Not running')] : ['no', t('Not set up')]
  const tile = (key: string, kind: Selected['kind'], id: string, name: string, desc: string, [tone, status]: [Tone, string]) =>
    <Tile key={key} icon={settingsIcon(key)} name={name} desc={desc} tone={tone} status={status} active={isActive(kind, id)} onClick={() => show({ kind, id })} />

  // A company card is ready when one of its connections says it is; the line under it says which, from the same state.
  const companyState = (c: Company): { ready: boolean; status: string; via: string } => {
    if (!data) return { ready: false, status: error ? t('Not known') : t('Checking…'), via: '' }
    const acc = c.account ? data.models[c.account.conn] : undefined
    const key = data.models[c.key.conn]
    const a = !!acc?.ready, k = !!key?.ready
    const via = a && k ? t('Connected with your account and an API key') : a ? t('Connected with your account') : k ? t('Connected with an API key')
      : key?.key_configured ? t('API key saved · not ready') : acc?.signed_in ? t('Signed in · not ready')
      : t(c.account ? 'Connect with your account or an API key' : 'Connect with an API key')
    return { ready: a || k, status: t(a || k ? 'Ready' : 'Not connected'), via }
  }
  const companyCard = (c: Company, compact = false) => {
    const state = companyState(c)
    return <CompanyCard key={c.id} mark={companyMark(c.icon, c.mono)} name={c.name} maker={t(c.maker)} via={compact ? undefined : state.via} ready={state.ready}
      status={state.status} active={isActive('company', c.id)} compact={compact} onClick={() => show({ kind: 'company', id: c.id })} />
  }
  // Older connections stay listed while their key is saved, so nobody loses one they set up.
  const others = OTHER_COMPANIES.filter(c => !c.onlyWhenSet || !!data?.models[c.key.conn]?.key_configured || !!keyEntry(c.key.env)?.configured)
  const othersReady = others.filter(c => companyState(c).ready).length

  // Local models: Ollama is its own connection; LM Studio and other servers run research steps through the local server
  // connection, whose saved address says which one it is.
  const localServer = data?.models.local_server
  const lmStudio = toolOf('lm_studio')
  const lmStudioUrl = lmStudio?.endpoint ? `${lmStudio.endpoint}/v1` : null
  const lmStudioInUse = !!lmStudioUrl && localServer?.base_url === lmStudioUrl
  const localReady: Record<string, boolean> = {
    ollama: !!data?.models.ollama?.ready,
    lm_studio: lmStudioInUse && !!localServer?.ready,
    local_server: !!localServer?.ready,
  }
  const localCards = [
    { id: 'ollama', name: 'Ollama', hint: 'ollama.com', mark: companyMark('ollama', undefined) },
    { id: 'lm_studio', name: 'LM Studio', hint: 'lmstudio.ai', mark: companyMark('lm_studio', undefined) },
    { id: 'local_server', name: t('Another local server'), hint: localServer?.base_url ?? t('llama.cpp, Jan, LocalAI, vLLM · enter its address'), mark: companyMark(undefined, undefined, <Plus size={16} strokeWidth={1.8} />) },
  ]
  // Document reading (not models): the PDF tools in the mockup's order.
  const docRows: { kind: Selected['kind']; id: string; name: string; what: string; status: [Tone, string] }[] = [
    { kind: 'pdf-reader', id: 'pymupdf', name: 'PDF reader', what: 'Reads the text of every PDF', status: pdfReaderStatus() },
    { kind: 'ocr-tool', id: 'tesseract', name: 'Scanned PDF reader (OCR)', what: 'Turns scanned pages into text', status: ocrStatus() },
    { kind: 'equation-reader', id: 'marker', name: 'Equation reader', what: 'Reads equations as LaTeX', status: readerStatus() },
  ]
  const saveLocalServer = (url: string) => {
    setServerBusy(true); setServerError('')
    api.saveLocalServer(url).then(result => {
      setData(current => current ? { ...current, models: { ...current.models, local_server: { ...result, connection: 'local_server' } } } : current)
      setServerDraft(null)
      toast('success', url ? t('Local server address saved.') : t('Local server address removed.'))
    }).catch((e: Error) => setServerError(e.message)).finally(() => setServerBusy(false))
  }
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
    { id: 'gemini', providers: ['gemini'], label: t('Gemini embeddings'),
      desc: withCode(t('{model} · sends titles, abstracts and passage text to Google'), { model: option('gemini')?.models[0] ?? 'gemini-embedding' }),
      body: <>
        <p className="local-tool-note">{t('Reads the question in any language. Needs a Google AI Studio key; a free key works.')}</p>
        {!option('gemini')?.available && <GeminiKeyPath />}
      </> },
    { id: 'builtin', providers: ['builtin'], label: t('This computer · built-in'),
      desc: withCode(t('{model} · reads English; for a question in another language it asks for one English sentence'), { model: 'bge-small-en-v1.5' }),
      body: <>
        {builtin && <BuiltinEmbeddingPanel builtin={builtin} dark={dark} onChanged={async () => { await loadBuiltin(); await loadSemantic() }} />}
      </> },
    { id: 'openai', providers: ['openai'], label: t('OpenAI embeddings'),
      desc: withCode(t('{model} · sends titles, abstracts and passage text to OpenAI'), { model: option('openai')?.models[0] ?? 'text-embedding-3-small' }) },
    { id: 'server', providers: ['ollama', 'lm_studio'], label: t('Local model server'), desc: t('An embedding model on Ollama or LM Studio') },
    { id: 'off', providers: ['off'], label: t('Off'), desc: t('Keyword search only; sources get no similarity score.') },
  ]
  const privacy = !semantic ? null : semantic.provider === 'off' ? t('Sources get no similarity score; passages are ranked by keyword match only. No text is sent anywhere.')
    : semantic.provider === 'gemini' ? t('Passage text is sent to Google. If your key is on Google’s free tier, which DEIXIS cannot detect, Google may use that text to improve its products.')
    : semantic.provider === 'openai' ? t('Passage text is sent to {service}.', { service: 'OpenAI' })
    : semantic.provider === 'builtin' ? t('For semantic search, no text leaves the computer.') : t('Passage text stays on this computer.')

  // ---- the connection sheet ----
  const sel = selected
  const company = sel?.kind === 'company' ? COMPANIES.find(c => c.id === sel.id) : undefined
  const provider = sel?.kind === 'provider' ? data?.providers.find(p => p.id === sel.id) : undefined
  // The sheet title carries the same mark as the card or tile it opened from.
  const sheetIcon = !sel ? null
    : company ? (company.icon ? <ConnectionIcon id={company.icon} /> : null)
    : sel.kind === 'local' ? settingsIcon(sel.id === 'local_server' ? 'server' : sel.id)
    : settingsIcon(sel.kind === 'ocr-tool' ? 'ocr' : sel.kind === 'pdf-reader' ? 'pymupdf' : sel.kind === 'reference-files' ? 'reference-files' : sel.id)
  const name = !sel ? ''
    : company ? company.name
    : sel.kind === 'local' ? (sel.id === 'local_server' ? t('Another local server') : localToolNames[sel.id] ?? sel.id)
    : sel.kind === 'provider' ? providerNames[sel.id] ?? sel.id
    : sel.kind === 'equation-reader' ? t('Equation reader (Marker)')
    : sel.kind === 'ocr-tool' ? t('OCR (Tesseract)')
    : sel.kind === 'pdf-reader' ? t('PDF reader (PyMuPDF)')
    : sel.kind === 'reference-files' ? t('BibTeX / RIS files')
    : sel.kind === 'zotero' ? 'Zotero'
    : sel.id
  const checkedLine = (key: string) => checked[key] && !checkFailed[key] ? <span className="status-chip is-configured">{t('checked {time}', { time: clock(checked[key]) })}</span> : null
  // A failed check and the reason a connection is not ready share one card under the status line.
  const reasonNotice = (key: string, reason?: ReactNode) => {
    const failed = checking !== key && checkFailed[key]
    return (failed || reason) && <Notice tone="attention">
      {failed && <p className="check-failed">{t('Could not check: {message}', { message: checkFailed[key] })}</p>}
      {reason && <p>{reason}</p>}
    </Notice>
  }
  const dmeta = (key: string, [tone, status]: [Tone, string], extra?: ReactNode, reason?: ReactNode) => <>
    <p className="dmeta">{checking === key ? <span><span className="spin" aria-hidden /> {t('Checking…')}</span> : <span className={`status-chip is-status ${tone === 'warn' ? 'is-warning' : tone === 'no' ? 'is-configured' : ''}`}>{status}</span>}{extra}{checking !== key && checkedLine(key)}</p>
    {reasonNotice(key, reason)}
  </>
  const checkButton = (key: string, label: string, run: () => Promise<unknown>, disabled = false, quiet = false) =>
    <button type="button" className={quiet ? 'ghost' : 'btn-pri'} disabled={disabled || checking !== null} onClick={() => runCheck(key, run)}>{checking === key ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t(label)}</button>
  // The Codex home this backend uses (DEIXIS_CODEX_HOME or the data folder's), single-quoted for a POSIX shell.
  const codexLogin = data?.codex_home ? `CODEX_HOME='${data.codex_home.replaceAll("'", "'\\''")}' codex login` : null
  const signInCommandOf = (id: string) => id === 'codex' ? codexLogin : id === 'claude' ? 'claude auth login' : id === 'copilot_cli' ? 'copilot login' : id === 'gemini_cli' ? 'gemini' : null
  const copy = (text: string) => { writeClipboard(text).then(() => toast('success', t('Command copied.')), () => toast('error', t('Could not copy; select the command and copy it.'))) }
  // A way's head: its label and the state of its own connection.
  const wayHead = (label: string, [tone, status]: [Tone, string], key?: string, tag?: ReactNode) => <div className="way-head">
    <h3>{label}</h3>{tag}
    {key && checking === key ? <span className="spin" aria-label={t('Checking…')} /> : <span className={`st ${tone}`}>{status}</span>}
    {key && checking !== key && checkedLine(key)}
  </div>

  // The account way: sign in with the subscription account through the tool DEIXIS runs for it (Claude Code, Codex CLI,
  // Copilot CLI, Gemini CLI); the tool's name and checks are in its details.
  const accountWay = (c: Company) => {
    const accountId = c.account!.conn
    const model = data?.models[accountId]
    const tool = toolOf(ACCOUNT_TOOLS[accountId].tool)
    const key = `account:${accountId}`
    const ownRun = signInRun?.tool === accountId ? signInRun.run : null
    const signInCommand = signInCommandOf(accountId)
    const status = accountStatus(accountId)
    const toolName = ACCOUNT_TOOLS[accountId].name
    return <section key="account" className={`way ${model?.ready ? 'is-on' : ''}`} aria-label={t(c.account!.label)}>
      {wayHead(t(c.account!.label), status, key)}
      <p className="way-desc">{t(c.account!.desc)}</p>
      {reasonNotice(key, model && !model.ready ? healthReasonText(model) : undefined)}
      <div className="acts">
        {signInCommand && <button type="button" className={model?.signed_in ? 'ghost' : 'btn-pri'} disabled={ownRun?.state === 'waiting'} onClick={() => startSignIn(accountId)}>
          {ownRun?.state === 'waiting' && <span className="spin" aria-hidden />}
          {ownRun && (ownRun.state === 'failed' || ownRun.state === 'timed_out') ? t('Try again') : model?.signed_in ? t('Sign in again') : t('Sign in')}
        </button>}
        {checkButton(key, 'Test the connection', () => refreshModel(accountId), !model, true)}
      </div>
      {ownRun?.state === 'waiting' && <p className="foot-note signin-wait" role="status">
        <span className="spin" aria-hidden />{t('A terminal window opened. Finish signing in there; this updates by itself.')}
      </p>}
      {ownRun && (ownRun.state === 'failed' || ownRun.state === 'timed_out') && ownRun.message && <p className="foot-note warn-t" role="alert">{ownRun.message}</p>}
      {ownRun && (ownRun.state === 'failed' || ownRun.state === 'timed_out') && signInCommand && <div className="signin-cmd">
        <p className="foot-note">{t('Run this in a terminal, then test the connection:')}</p>
        <div className="cmd-row"><code className="field mono">{signInCommand}</code><button type="button" className="ghost" onClick={() => copy(signInCommand)}><Copy aria-hidden />{t('Copy')}</button></div>
      </div>}
      {tool && (!model || !tool.installed) && <LocalToolDetails key={tool.id} tool={tool} dark={dark} onChanged={reloadTools} />}
      {!model && data && <p className="foot-note">{t('No model connection is set up for it in this version of DEIXIS; the tool on this computer is shown above.')}</p>}
      {model && <details className="way-more">
        <summary><ChevronRight size={14} aria-hidden />{t('Details')}</summary>
        <p className="foot-note">{t(accountId === 'codex'
          ? 'Uses the account you sign in with through Codex CLI. DEIXIS keeps this sign-in apart from your usual Codex one and stores no password.'
          : accountId === 'gemini_cli' ? 'Uses the Google account you are signed in with in Gemini CLI. DEIXIS keeps no password or token of its own.'
          : accountId === 'copilot_cli' ? 'Uses the GitHub account you are signed in with in Copilot CLI. DEIXIS keeps no password or token of its own.'
          : 'Uses the account you are signed in with in Claude Code. DEIXIS keeps no password or token of its own.')}</p>
        <p className="foot-note">{t(accountId === 'codex' ? 'Codex only writes text for DEIXIS: its tools, add-ons and instruction files are turned off.'
          : accountId === 'claude' ? 'Claude Code only writes text for DEIXIS: its tools, add-ons and instruction files are turned off.'
          : accountId === 'copilot_cli' ? 'Copilot CLI only writes text for DEIXIS: its tools, add-ons and instruction files are turned off. Each model uses your Copilot plan’s requests at the rate GitHub sets for it.'
          : 'Gemini CLI only writes text for DEIXIS: DEIXIS starts it with its own settings, which turn off its tools, MCP servers, extensions and instruction files, and stops a step if the CLI reports any tool use.')}</p>
        <div className="connection-checks">
          {check(toolName, model.installed ? model.cli_version ?? t('installed') : t('not found'))}
          {check(t('Signed in'), model.signed_in ? (model.plan_type ?? model.account_type ? t('yes · {plan}', { plan: model.plan_type ?? model.account_type ?? '' }) : t('yes')) : t('no'))}
          {accountId !== 'gemini_cli' && check(t('Instruction files used'), model.isolation ? String(model.isolation.instruction_sources) : t('not checked'))}
          {accountId !== 'gemini_cli' && check(t('Add-ons with tools'), model.isolation ? (model.isolation.live_mcp_servers.join(', ') || t('none')) : t('not checked'))}
        </div>
        {model.catalogue === 'fixed' && <p className="foot-note">{t('Gemini CLI cannot list its models, so this list is fixed in DEIXIS. A step that another model answers is stopped.')}</p>}
        <ModelCatalogue model={model} />
      </details>}
    </section>
  }
  // The key way: the key field of the company's API connection, with that connection's own state.
  const keyWay = (c: Company) => {
    const way = c.key
    const model = data?.models[way.conn]
    const entry = keyEntry(way.env)
    const status: [Tone, string] = !data || !credentials ? loading : model?.ready ? ['ok', t('Ready')] : entry?.configured && model ? modelStatus(model) : ['no', t('No key entered')]
    const effect = way.env === 'OPENAI_API_KEY' ? t('Research steps with this key, and semantic search with OpenAI, stop until a new key is added.')
      : way.env === 'GEMINI_API_KEY' ? t('Research steps with this key, and semantic search with Gemini, stop until a new key is added.')
      : t('This connection stops working until a new key is added.')
    return <section key="key" className={`way ${model?.ready ? 'is-on' : ''}`} aria-label={t(way.label ?? 'With an API key')}>
      {wayHead(t(way.label ?? 'With an API key'), status, undefined, c.keyFirst ? <span className="st rec">{t('Recommended')}</span> : undefined)}
      <p className="way-desc">{linkify(t(way.desc ?? PAY_AS_YOU_GO, { site: t(way.site) }))}</p>
      {entry?.configured && model && !model.ready && reasonNotice(`key:${way.conn}`, healthReasonText(model))}
      {credentials && <KeyField key={way.env} env={way.env} entry={entry} keychain={credentials.keychain} label={t('Key')} service={way.service ?? c.name}
        removeEffect={effect} onSaved={reloadAfterKeyChange} />}
      {model && (model.models?.length || way.conn === 'gemini') ? <details className="way-more">
        <summary><ChevronRight size={14} aria-hidden />{t('Details')}</summary>
        {way.conn === 'gemini' && <div className="connection-checks">
          {/* From the saved semantic search provider, not from the key alone: another provider or Off may be chosen. */}
          {check(t('Semantic passage search'), !semantic ? t('not known') : semantic.provider === 'gemini' ? t('on · passage text is sent to Google')
            : model.key_configured ? t('off · another provider is chosen') : t('off'))}
        </div>}
        <ModelCatalogue model={model} />
      </details> : null}
    </section>
  }
  const soonWay = (label: string) => <section key="soon" className="way is-soon" aria-label={t(label)}>
    {wayHead(t(label), ['no', t('Coming soon')])}
    <p className="way-desc">{t('Signing in with a subscription account is not available for this model yet.')}</p>
  </section>
  // A local server's address (read-only: each app's default), its tool state and the embedding model semantic search
  // may use from it.
  const serverBlock = (server: LocalTool) => <section className="server-block" aria-label={server.name || localToolNames[server.id]}>
    {server.endpoint && <div className="lbl">{t('Server address')}<code className="field mono">{server.endpoint}</code></div>}
    <LocalToolDetails tool={server} dark={dark} onChanged={reloadTools} refresh={false} />
    {server.endpoint && <p className="foot-note">{t('The address is the one the app uses by default; this version of DEIXIS cannot change it.')}</p>}
    {/* The same choice as the Local model server row under Semantic search: choosing a model saves it as the provider. */}
    {(() => {
      const choices = serverChoices.filter(c => c.provider === server.id)
      const mine = serverChosen && chosen!.provider === server.id
      return <label className="lbl">{t('Embedding model for semantic search')}
        <select className="select server-embedding" disabled={saving || !choices.length} value={mine ? `${chosen!.provider}|${chosen!.model ?? ''}` : ''}
          onChange={e => { if (!e.target.value) return; const [p, ...m] = e.target.value.split('|'); chooseSemantic(p as SemanticSearchProvider, m.join('|')) }}>
          {!mine && <option value="">{t(choices.length ? 'Not used for semantic search' : 'No embedding model listed')}</option>}
          {choices.map(c => <option key={`${c.provider}|${c.model}`} value={`${c.provider}|${c.model}`}>{c.label}</option>)}
        </select>
      </label>
    })()}
  </section>
  const localCheck = (conn: string | null) => Promise.all([...(conn ? [refreshModel(conn)] : []), loadTools(true, true), loadSemantic(true)])
  let body: ReactNode = null
  if (company) {
    const ways = company.keyFirst
      ? [keyWay(company), company.account && accountWay(company)]
      : [company.account ? accountWay(company) : company.soon ? soonWay(company.soon) : null, keyWay(company)]
    body = <>
      <p className="foot-note is-ink">{t(company.intro ?? (company.account ? 'Either way is enough. If you have a subscription, signing in with your account is the easiest.' : 'This model connects with an API key only for now.'))}</p>
      {ways}
      {company.account && <p className="foot-note">{t('If both are connected, each appears as its own choice in the model lists. A research uses the one you choose; DEIXIS does not switch between them by itself.')}</p>}
    </>
  } else if (sel?.kind === 'local' && sel.id === 'ollama') {
    const model = data?.models.ollama
    const tool = toolOf('ollama')
    body = <>
      {dmeta('local:ollama', model ? modelStatus(model) : data ? unknown : loading, undefined, model && !model.ready ? healthReasonText(model) : undefined)}
      <p className="foot-note is-ink">{t('DEIXIS uses Ollama on this computer, so no key is needed. Open the Ollama app or run `ollama serve`, then download a model with `ollama pull`.')}</p>
      <div className="acts">{checkButton('local:ollama', 'Test', () => localCheck(model ? 'ollama' : null))}</div>
      {tool && serverBlock(tool)}
      {model && <ModelCatalogue model={model} />}
    </>
  } else if (sel?.kind === 'local' && sel.id === 'lm_studio') {
    const status: [Tone, string] = lmStudioInUse && localServer ? modelStatus(localServer) : !lmStudio ? (toolsError ? unknown : loading)
      : lmStudio.running ? ['no', t('Running')] : lmStudio.installed ? ['no', t('Not running')] : ['no', t('Not installed')]
    body = <>
      {dmeta('local:lm_studio', status, undefined, lmStudioInUse && localServer && !localServer.ready ? healthReasonText(localServer) : undefined)}
      <p className="foot-note is-ink">{t('LM Studio runs models on this computer. Research steps reach it through its local server address; semantic search can use one of its embedding models.')}</p>
      {serverError && <Notice tone="error"><p>{serverError}</p></Notice>}
      <div className="acts">
        {checkButton('local:lm_studio', 'Test', () => localCheck(lmStudioInUse ? 'local_server' : null))}
        {lmStudioUrl && lmStudio?.installed && !lmStudioInUse && <button type="button" className="ghost" disabled={serverBusy || !lmStudio?.running} onClick={() => saveLocalServer(lmStudioUrl)}
          title={lmStudio?.running ? undefined : t('Start LM Studio’s local server first')}>{t('Use for research steps')}</button>}
      </div>
      {lmStudioInUse && <p className="foot-note">{t('Research steps use LM Studio at {address}.', { address: lmStudioUrl ?? '' })}</p>}
      {lmStudio && serverBlock(lmStudio)}
      {lmStudioInUse && localServer && <ModelCatalogue model={localServer} />}
    </>
  } else if (sel?.kind === 'local' && sel.id === 'local_server') {
    const saved = localServer?.base_url ?? ''
    const field = serverDraft ?? saved
    const changed = field.trim().replace(/\/+$/, '') !== saved
    body = <>
      {dmeta('local:local_server', localServer ? (saved ? modelStatus(localServer) : ['no', t('No address entered')]) : data ? unknown : loading, undefined,
        localServer && saved && !localServer.ready ? healthReasonText(localServer) : undefined)}
      <p className="foot-note is-ink">{t('For llama.cpp, Jan, LocalAI, vLLM or any server on this computer that answers like the OpenAI API. Enter the address its models list is under, usually ending in /v1.')}</p>
      <form className="key-box" onSubmit={e => { e.preventDefault(); if (changed && field.trim()) saveLocalServer(field.trim()) }}>
        <label className="lbl" htmlFor="local-server-url">{t('Server address')}
          <input id="local-server-url" className="field" type="url" inputMode="url" spellCheck={false} autoComplete="off" value={field} disabled={serverBusy}
            placeholder="http://127.0.0.1:8080/v1" onChange={e => { setServerDraft(e.target.value); setServerError('') }} />
        </label>
        <p className="foot-note">{t('Only a server on this computer is accepted: 127.0.0.1, localhost or [::1]. No text leaves the computer.')}</p>
        {serverError && <Notice tone="error"><p>{serverError}</p></Notice>}
        <div className="acts">
          <button type="submit" className="btn-pri" disabled={serverBusy || !changed || !field.trim()}>{serverBusy ? <span className="spin" aria-hidden /> : <Save aria-hidden />}{t(serverBusy ? 'Saving…' : 'Save and test')}</button>
          {saved && <button type="button" className="ghost" disabled={serverBusy} onClick={() => saveLocalServer('')}>{t('Remove')}</button>}
          {saved && checkButton('local:local_server', 'Test', () => refreshModel('local_server'), serverBusy, true)}
        </div>
      </form>
      {localServer && saved && <ModelCatalogue model={localServer} />}
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
        ? linkify(t('Works without a key. A free key from openalex.org gives DEIXIS its own daily budget.'))
        : !env ? (MAILTO_PROVIDERS.has(provider.id) ? t('No key needed. DEIXIS adds your contact email to its requests, as the service asks.') : t('No key needed.'))
        : t(provider.note)}</p>
      {env && providerKeySignup[id] && <p className="foot-note key-signup">{linkify(t(providerKeySignup[id].steps))} <a href={providerKeySignup[id].url} target="_blank" rel="noopener noreferrer">{t('Get a key')}</a></p>}
      {env && credentials && <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain} service={providerNames[provider.id] ?? provider.id}
        label={t(provider.id === 'openalex' ? 'API key (optional, free from openalex.org)' : 'API key')}
        removeEffect={t('Requests that need this key stop until you add one again.')} onSaved={reloadAfterKeyChange} />}
      {env && credentials && !keyEntry(env)?.configured && providerNoKey[provider.id] && <Notice tone="attention">{t(providerNoKey[provider.id])}</Notice>}
      {keyless && <div className="acts">{checkButton(key, 'Test', () => api.testProvider(id).then(result => { setProviderTests(old => ({ ...old, [id]: result })); return result }))}</div>}
      {test && !test.contact_email_sent && <p className="foot-note">{t('Sent without a contact email; none is set in Profile.')}</p>}
      {MAILTO_PROVIDERS.has(provider.id) && <p className="foot-note"><a href="#/settings/profile">{t('Set the contact email in Profile')}</a></p>}
      <div className="connection-checks">{check(t('Used for'), providerUse[provider.id] ? t(providerUse[provider.id]) : providerRole(provider.role))}</div>
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
      {ocrTool && <OcrToolDetails tool={ocrTool} onChanged={() => loadOcr()} />}
    </>
  } else if (sel?.kind === 'pdf-reader') {
    body = <>
      {dmeta('pdf-reader', pdfReaderStatus())}
      {pdfReader && <PdfReaderDetails reader={pdfReader} />}
    </>
  } else if (sel?.kind === 'zotero') {
    body = <>
      {dmeta('zotero', zoteroStatus())}
      <p className="foot-note is-ink">{t('Import a collection from Add sources on the home page or from a research’s Sources panel. Your Zotero library is never changed.')}</p>
      <section className="zotero-route">
        <div className="zotero-route-head"><h3>{t('This computer')}</h3>{zotero && <span className={`status-chip is-status ${zotero.installed && zotero.running && zotero.local_api ? '' : 'is-configured'}`}>
          {t(!zotero.installed ? 'Not installed' : !zotero.running ? 'Not running' : zotero.local_api ? 'Local API on' : 'Local API off')}</span>}</div>
        <div className="acts">{checkButton('zotero', 'Find it on this computer', () => loadTools(true, true))}</div>
        {zotero && <LocalToolDetails tool={zotero} dark={dark} onChanged={reloadTools} refresh={false} chip={false} />}
      </section>
      {credentials && <section className="zotero-route">
        <div className="zotero-route-head"><h3>zotero.org</h3>{zotero && <span className={`status-chip is-status ${zotero.web_configured ? '' : 'is-configured'}`}>{t(zotero.web_configured ? 'Key and user ID saved' : 'Not set up')}</span>}</div>
        <p className="foot-note is-ink">{linkify(t('To import from zotero.org, create a read-only key at zotero.org/settings/keys. Your user ID is shown on the same page.'))}</p>
        {(['ZOTERO_API_KEY', 'ZOTERO_LIBRARY_ID'] as const).map(env => <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain}
          plain={env === 'ZOTERO_LIBRARY_ID'} note={env === 'ZOTERO_LIBRARY_ID'} label={t(env === 'ZOTERO_API_KEY' ? 'zotero.org API key' : 'zotero.org user ID')} service="zotero.org"
          removeEffect={t('Importing from zotero.org stops until you add it again.')} onSaved={() => { reloadAfterKeyChange(); void reloadTools() }} />)}
      </section>}
    </>
  } else if (sel?.kind === 'reference-files') {
    body = <>
      <p className="foot-note is-ink">{t('Adds the entries of a .bib or .ris file to the Library. Entries whose DOI OpenAlex or Crossref confirms use that record; the rest are kept as you wrote them, marked as not confirmed.')}</p>
      <ReferenceFileImport />
    </>
  }

  return <>
    {error && <Notice tone="error">{error}</Notice>}

    <p className="models-intro" data-panel="models">{t('Connect the model that runs the research steps. If you have a subscription, sign in with your account; if not, enter an API key. One is enough.')}</p>
    <section className="co-group" data-panel="models" aria-labelledby="model-connections">
      <h2 id="model-connections" tabIndex={-1}>{t('Model connections')}</h2>
      <div className="co-grid" data-group="main">{MAIN_COMPANIES.map(c => companyCard(c))}</div>
    </section>

    <section className="co-group" data-panel="models" aria-labelledby="other-models">
      <h2 id="other-models"><button type="button" className="co-fold" aria-expanded={showOthers} aria-controls="other-models-grid" onClick={() => setShowOthers(v => !v)}>
        <ChevronRight size={16} aria-hidden />{t('Other models')}{' '}<span>{data ? t('· {n} · {ready} ready', { n: others.length, ready: othersReady }) : t('· {n}', { n: others.length })}</span>
      </button></h2>
      {showOthers && <div className="co-grid" id="other-models-grid" data-group="others">{others.map(c => companyCard(c, true))}</div>}
    </section>

    <section className="co-group" data-panel="models" aria-labelledby="local-models">
      <h2 id="local-models">{t('Local models')}</h2>
      <p className="co-note">{t('They run on this computer. No account or key is needed; Ollama and LM Studio are found by themselves while their app is open.')}</p>
      {toolsError && <Notice tone="error">{toolsError}</Notice>}
      <div className="co-grid" data-group="local">{localCards.map(card => <CompanyCard key={card.id} mark={card.mark} name={card.name} maker={card.hint} ready={localReady[card.id]}
        status={!data ? (error ? t('Not known') : t('Checking…')) : t(localReady[card.id] ? 'Ready' : 'Not connected')} active={isActive('local', card.id)} compact
        onClick={() => show({ kind: 'local', id: card.id })} />)}</div>
      <p className="co-note">{t(LOCAL_TRY)}</p>
    </section>

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

    {defaults}
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

    <section className="doc-readers" data-panel="models" aria-labelledby="document-reading">
      <div className="co-group-head"><h2 id="document-reading">{t('Document reading')}</h2><p className="co-note">{t('Not models: tools that take the text out of PDFs.')}</p></div>
      <ul className="doc-list" data-group="documents">{docRows.map(row => {
        const [tone, status] = row.status
        return <li key={row.kind}><button type="button" className={isActive(row.kind, row.id) ? 'on' : ''} onClick={() => show({ kind: row.kind, id: row.id })}>
          <span><b>{t(row.name)}</b><small>{t(row.what)}</small></span><span className={`st ${tone}`}>{status}</span>
        </button></li>
      })}</ul>
    </section>

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
        <SheetHeader><SheetTitle>{sheetIcon}<span>{name}</span></SheetTitle><SheetDescription className="sr-only">{company ? `${company.name} · ${t(company.maker)}` : t('{name} details', { name })}</SheetDescription></SheetHeader>
        <div className="connection-body mk pad detail">{body}</div>
      </SheetContent>
    </Sheet>
  </>
}
