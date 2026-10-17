import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowUpRight, Ban, BadgeCheck, ChevronRight, CircleCheck, Cloud, Copy, Cpu, Download, FileLock, FileText, FileUp, HardDrive, Info, KeyRound, Laptop, MemoryStick, LoaderCircle, Package, PenLine, Plus, RefreshCw, RotateCw, Save, ScanText, Server, ShieldCheck, Trash2, TriangleAlert, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ConfirmDialog } from './ConfirmDialog'
import { DataLocationCard } from './DataLocation'
import { api, ApiError, libraryImportsApi, type AccountSignIn, type BuiltinModel, type BuiltinModels, type Connections, type Credentials, type KeyEntry, type KeyTest, type Keychain, type EquationReader, type LocalTool, type Mathpix, type OllamaUpdates, type OcrTool, type PdfReader, type ToolUpdate, type LocalTools, type ProviderTest, type ModelHealth, type ReferenceImport, type Reranking, type RerankProvider, type SemanticSearch, type SemanticSearchOption, type SemanticSearchProvider } from './api'
import { useToast } from './Toast'
import { ocrLanguagesText } from './ocr'
import { t, uiLocale } from './i18n'
import { serviceErrorSentence, healthReasonText, installReasonText, toolActionError, credentialFailureText, keychainLabel, localToolIcon, localToolNames, providerRole, reasoningLabel } from './labels'
import { ConnectionIcon } from './connectionIcons'
import { writeClipboard } from './clipboard'
import { Notice } from './Notice'
import { createRequestOrder } from './requestOrder'
import { gaveNoAnswer, isLeft } from './readLimit'
import { useLeaving } from './useLeaving'

const providerNames: Record<string, string> = {
  semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', biorxiv: 'bioRxiv', pubmed: 'PubMed', openalex: 'OpenAlex', scopus: 'Scopus', ieee_xplore: 'IEEE Xplore', core: 'CORE', serpapi: 'SerpApi',
}
// Providers that take their own key; env names come from the credentials contract.
const providerKeyEnv: Record<string, string> = { openalex: 'OPENALEX_API_KEY', biorxiv: 'OPENALEX_API_KEY', semantic_scholar: 'S2_API_KEY', pubmed: 'NCBI_API_KEY', ieee_xplore: 'IEEE_API_KEY', scopus: 'SCOPUS_API_KEY', core: 'CORE_API_KEY', serpapi: 'SERPAPI_API_KEY' }
// The mockup's order comes first (plan ST7); every other registered connector follows in the registry's order.
const PROVIDER_ORDER = ['openalex', 'semantic_scholar', 'crossref', 'scopus', 'arxiv']
// What the fast path asks each source for (fast_search.py, fast_read.py, documents/acquisition.py). The fast path sends
// no query to arXiv, PubMed or IEEE Xplore (fast_search drops them as openalex_only) and calls SerpApi nowhere
// (flow.py passes web_search=False).
const providerUse: Record<string, string> = {
  openalex: 'Search, citation chain and PDF lookup', semantic_scholar: 'Abstracts; bulk search in Detailed mode',
  crossref: 'Abstracts, metadata checks and PDF lookup', scopus: 'Abstracts, once its full view is confirmed',
  arxiv: 'Not searched now', biorxiv: 'Not searched on its own; OpenAlex brings its preprints',
  pubmed: 'Not searched now', ieee_xplore: 'Not searched now', core: 'PDF lookup by DOI', serpapi: 'Not used now',
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
  key?: KeyWay  // absent: the company connects with an account only
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
    // GitHub retired GitHub Models, its token way, on 30 Jul 2026 (D59); Copilot CLI is a separate service.
    account: { conn: 'copilot_cli', label: 'With your GitHub account', desc: 'If you have a Copilot subscription. Free for students and teachers.' } },
  { id: 'grok', name: 'Grok', maker: 'xAI', icon: 'grok', soon: 'With your SuperGrok account', key: { conn: 'grok', env: 'XAI_API_KEY', site: 'console.x.ai', service: 'xAI' } },
  { id: 'mistral', name: 'Mistral', maker: 'Mistral AI', icon: 'mistral', soon: 'With your Mistral account', key: { conn: 'mistral', env: 'MISTRAL_API_KEY', site: 'console.mistral.ai' } },
]
const META_SITE = 'the Meta Model API (US only for now)'
const OTHER_COMPANIES: Company[] = [
  { id: 'openrouter', name: 'OpenRouter', maker: 'One key, many models', mono: 'OR', key: { conn: 'openrouter', env: 'OPENROUTER_API_KEY', site: 'openrouter.ai/keys' } },
  { id: 'muse', name: 'Muse', maker: 'Meta', icon: 'muse_spark', key: { conn: 'muse_spark', env: 'MODEL_API_KEY', site: META_SITE } },
  { id: 'mimo', name: 'MiMo', maker: 'Xiaomi', mono: 'Xi', key: { conn: 'mimo', env: 'MIMO_API_KEY', site: 'platform.xiaomimimo.com' } },
  { id: 'qwen', name: 'Qwen', maker: 'Alibaba', icon: 'qwen', key: { conn: 'qwen', env: 'DASHSCOPE_API_KEY', site: 'modelstudio.console.alibabacloud.com' } },
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
  mark: ReactNode; name: string; maker: ReactNode; via?: string; ready: boolean; status: string; active: boolean; compact?: boolean; onClick: () => void
}) {
  return <button type="button" className={`co-card ${compact ? 'is-compact' : ''} ${active ? 'on' : ''}`} onClick={onClick}>
    <span className="co-head">{mark}<span className="co-name"><b>{name}</b><small>{maker}</small></span><span className={`st ${ready ? 'ok' : 'no'}`}>{status}</span></span>
    {via && <span className="co-via">{via}</span>}
  </button>
}
const formatBytes = (bytes: number) => bytes / 1e9 >= 1 ? t('{gb} GB', { gb: (bytes / 1e9).toFixed(1) }) : t('{mb} MB', { mb: Math.round(bytes / 1e6) })
const clock = (iso: string | number) => new Date(iso).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })
const day = (iso: string) => new Date(iso).toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short' })

// Settings icons, drawn in black and white (Settings.css): brand marks where connectionIcons.tsx has one, a plain glyph otherwise.
const glyph = (icon: ReactNode) => <span className="connection-icon" aria-hidden="true">{icon}</span>
const GLYPHS: Record<string, ReactNode> = {
  ocr: glyph(<ScanText strokeWidth={1.8} />), marker: <ConnectionIcon id="marker" />, mathpix: glyph(<Cloud strokeWidth={1.8} />), pymupdf: <ConnectionIcon id="pymupdf" />, servers: glyph(<Server strokeWidth={1.8} />),
  server: glyph(<Server strokeWidth={1.8} />), 'reference-files': glyph(<FileText strokeWidth={1.8} />), off: glyph(<Ban strokeWidth={1.8} />),
  voyage: <ConnectionIcon id="voyage" />, cohere: <ConnectionIcon id="cohere" />, jina: <ConnectionIcon id="jina" />,
  zeroentropy: <ConnectionIcon id="zeroentropy" />,
}
const settingsIcon = (key: string) => GLYPHS[key] ?? <ConnectionIcon id={localToolIcon(key)} />

type Selected = { kind: 'company' | 'local' | 'semantic' | 'equation-reader' | 'mathpix' | 'ocr-tool' | 'pdf-reader' | 'provider' | 'zotero' | 'reference-files'; id: string }
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

// Where a saved key lives (E5, A6): the system keychain, this run's memory when there is none, or the file the person chose.
function keyHome(keychain: Keychain) {
  const name = keychainLabel(keychain.kind)
  return keychain.mode === 'session' ? { where: t('kept for this session only'), note: t('Kept in memory for this session only, never in research files or exports.') }
    : keychain.mode === 'file' ? { where: t('stored unencrypted in your data folder'), note: t('Stored unencrypted in your data folder, never in research files or exports.') }
    : { where: t('stored in {keychain}', { keychain: name }), note: t('Stored in {keychain}, never in research files or exports.', { keychain: name }) }
}

// The keychain's refusals come as a cause code; the person reads it in their language, with the keychain named for their system.
function keychainError(e: Error, keychain: Keychain): string {
  if (!(e instanceof ApiError)) return e.message
  return e.code ? credentialFailureText(e.code, keychainLabel(keychain.kind)) : e.message
}

// With no system keychain a key lives in memory for this run; the person can choose an unencrypted file instead (A6).
function KeyStore({ keychain, onChanged }: { keychain: Keychain; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (keychain.mode === 'keychain') return null
  const file = keychain.mode === 'file'
  function choose(enabled: boolean) {
    setBusy(true); setError('')
    api.setFileStore(enabled).then(() => onChanged()).catch((e: Error) => setError(keychainError(e, keychain))).finally(() => setBusy(false))
  }
  return <>
    <Notice tone="attention">
      <p>{file ? t('Keys are stored unencrypted in a file in your data folder that only you can read. A system keychain is safer: GNOME → gnome-keyring, KDE → KWallet.')
        : t('We’re using this key for this session; to keep it, install the system keychain: GNOME → gnome-keyring, KDE → KWallet.')}</p>
      <div className="acts"><button type="button" className="ghost" disabled={busy} onClick={() => choose(!file)}>{t(file ? 'Stop storing keys in a file' : 'Store keys in a file instead (unencrypted)')}</button></div>
    </Notice>
    {keychain.file_error && <Notice tone="error"><p>{t('The key file in your data folder cannot be read, so DEIXIS left it as it is and changes no key until it is fixed or removed.')}</p></Notice>}
    {error && <Notice tone="error"><p>{error}</p></Notice>}
  </>
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
  const [running, setRunning] = useState(0)  // researches running with this key, asked when the remove question opens (E13)
  const toast = useToast()
  if (!entry) return null
  const id = `key-${env}`
  // A key saved here replaces one from the shell; removing it brings the shell key back.
  const fromShell = entry.source === 'environment'
  // D29: with no system keychain a shell key keeps its note and cannot be replaced, though other keys can be kept for the session.
  if (fromShell && !keychain.available) return <p className="foot-note">{t('This key is set outside DEIXIS; change or remove it where it was set.')}</p>
  const inDotenv = entry.source === 'dotenv'
  const home = keyHome(keychain)
  const where = inDotenv ? '' : fromShell ? t('set outside DEIXIS') : home.where
  const typed = value.trim()

  // The third state: the key is saved but no request showed that it works. An API without a model list says so; any other
  // test that did not get an answer keeps the service's own reason (quota, network, server error).
  const notVerifiedSentence = (test: KeyTest) => test.status === 'unverified'
    ? t('{service} has no request that checks a key on its own. The first research step will try it.', { service })
    : test.status === 'rejected' ? t('{service} did not accept this key. Enter it again.', { service })
    : serviceErrorSentence({ kind: test.kind, service, resetAt: test.reset_at, effect: 'settings' })
  function test() {
    setBusy(true); setFormError('')
    api.testCredential(env).then(result => {
      toast(result.status === 'ok' ? 'success' : 'warning', result.status === 'ok' ? t('The key works.') : notVerifiedSentence(result))
      onSaved()
    }).catch((e: Error) => setFormError(keychainError(e, keychain))).finally(() => setBusy(false))
  }
  function save() {
    setBusy(true); setFormError('')
    api.saveCredential(env, typed).then(result => {
      setValue(''); onSaved()
      toast(result.test && result.test.status !== 'ok' ? 'warning' : 'success', result.test && result.test.status !== 'ok'
        ? t('Key saved, not verified.') + ' ' + notVerifiedSentence(result.test)
        : t('Key saved.'))
    }).catch((e: Error) => setFormError(e instanceof ApiError && e.code === 'credential_test_failed'
      ? t('The key was not saved.') + ' ' + (keyRefusal(service, env, e.details?.http_status) ?? serviceErrorSentence({ kind: e.details?.kind, service, resetAt: e.details?.reset_at, effect: 'settings' }))
      : keychainError(e, keychain))).finally(() => setBusy(false))
  }
  function ask() {
    setRunning(0); setAsking(true)
    api.credentialInUse(env).then(result => setRunning(result.running_researches)).catch(() => {})
  }
  function remove() {
    setBusy(true); setFormError('')
    api.removeCredential(env).then(() => { setAsking(false); onSaved(); toast('success', t('Key removed.')) })
      .catch((e: Error) => setFormError(keychainError(e, keychain))).finally(() => setBusy(false))
  }
  const primary = typed ? (entry.testable ? 'Save and test' : 'Save') : entry.configured && entry.testable ? 'Test' : null
  return <form className="key-box" onSubmit={e => { e.preventDefault(); if (typed) save(); else if (primary) test() }}>
    <label className="lbl" htmlFor={id}>{label}
      <input id={id} className="field" type={plain ? 'text' : 'password'} inputMode={plain ? 'numeric' : undefined} spellCheck={false} value={value} disabled={busy}
        aria-invalid={formError ? true : undefined} aria-describedby={formError ? `${id}-error` : undefined}
        // A browser or password manager would fill a saved web password here and it would be saved as the key.
        autoComplete={plain ? 'off' : 'new-password'} data-1p-ignore data-lpignore="true" data-bwignore data-form-type="other"
        placeholder={entry.configured ? `${entry.last4 ? `••••••••${entry.last4}` : '••••••••••••'} ${where}`.trim() : t(plain ? 'Type your user ID' : 'Paste your key')} onChange={e => { setValue(e.target.value); setFormError('') }} />
    </label>
    {entry.keychain_unavailable && <Notice tone="attention"><p>{t('The system keychain did not answer, so your saved key was not used this time. It may be fine: restart DEIXIS once the keychain is unlocked.')}</p></Notice>}
    {entry.keychain_pending && <Notice tone="attention"><p>{t('The system keychain has not answered the last change to this key yet. The key shows its real state once it does; reopen Settings in a moment.')}</p></Notice>}
    {entry.broken && <Notice tone="attention"><p>{t('This saved key is broken and was not used. Enter it again.')}</p></Notice>}
    {entry.configured && entry.verification === 'pending' && <p className="foot-note"><Info aria-hidden />{t('Saved, not verified: no request has shown that this key works yet.')}</p>}
    {entry.configured && entry.verification === 'rejected' && <Notice tone="attention"><p>{t('{service} did not accept this key. Enter it again.', { service })}</p></Notice>}
    {note && <p className="foot-note key-note"><ShieldCheck aria-hidden />{fromShell && `${t('This key is set outside DEIXIS. A key saved here replaces it.')} `}{inDotenv ? t('Never stored in research files or exports.') : home.note}
      {entry.testable && ` ${t('A new key is tested with one short request before it is saved.')}`}</p>}
    {note && <KeyStore keychain={keychain} onChanged={onSaved} />}
    {formError && <Notice tone="error"><p id={`${id}-error`}>{formError}</p></Notice>}
    <div className="acts">
      {primary && <button type="submit" className="btn-pri" disabled={busy}>{busy ? <span className="spin" aria-hidden /> : typed ? <Save aria-hidden /> : <CircleCheck aria-hidden />}{t(busy ? (typed ? (entry.testable ? 'Testing and saving…' : 'Saving…') : 'Testing…') : primary)}</button>}
      {entry.configured && !fromShell && !asking && <button type="button" className="ghost" disabled={busy} onClick={ask}>{t(plain ? 'Remove ID' : 'Remove key')}</button>}
    </div>
    {asking && <RemoveNotice busy={busy} onRemove={remove} onKeep={() => setAsking(false)}
      text={t(plain ? 'Remove the ID for {name}?' : 'Remove the key for {name}?', { name: service }) + ' ' + (entry.shell_fallback ? t('DEIXIS goes back to the key that is set outside it.') : removeEffect)
        + (running > 0 ? ' ' + t(running === 1 ? '{n} research is running with this key. A step already sent finishes with it. Later steps use a key set outside DEIXIS, or none.' : '{n} researches are running with this key. A step already sent finishes with it. Later steps use a key set outside DEIXIS, or none.', { n: running }) : '')} />}
  </form>
}

// A path that may break after its separators (Windows paths use backslashes).
const wrapPath = (path: string) => path.split(/([\\/])/).map((part, i) => <span key={i}>{part}<wbr /></span>)

// A refused install that names the missing program by code reads in the person's language; any other refusal keeps its own line.
const installError = (e: Error, tool: LocalTool) => e instanceof ApiError ? toolActionError(e, tool.install.manager) : e.message

// Warnings are left out: brew prints them for unrelated taps, so they rarely explain a failed install.
function errorLines(output: string): string[] {
  // A failed install that could not run carries a marker line, never the exception; it reads in the person's language.
  const marker = output.includes('[could_not_run]') ? [t('The install stopped before it finished. Check the free disk space and your network connection, then try again.')] : []
  return [...marker, ...output.split('\n').map(line => line.trim()).filter(line => /\berror\b|fatal|npm err!|permission denied|could not|not found/i.test(line)).slice(0, 3)]
}

function LocalToolDetails({ tool, dark, onChanged, refresh = true, chip = true }: { tool: LocalTool; dark: boolean; onChanged: () => Promise<void>; refresh?: boolean; chip?: boolean }) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const toast = useToast()
  const name = tool.name || localToolNames[tool.id] || tool.id
  const running = tool.job?.status === 'running'
  // Ollama on macOS: Homebrew's CLI alone starts no server, so the app from ollama.com is offered until one answers.
  const offerApp = tool.app_installed === false && !tool.running
  const offerInstall = !tool.installed || offerApp
  function install() {
    setBusy(true)
    api.installLocalTool(tool.id).then(() => { setConfirmOpen(false); onChanged() }).catch((e: Error) => toast('error', installError(e, tool))).finally(() => setBusy(false))
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
      {tool.path && <><dt>{t('Path')}</dt><dd className="local-tool-path">{wrapPath(tool.path)}</dd></>}
      {tool.other_copies?.map(copy => <Fragment key={copy}><dt>{t('Also found')}</dt><dd className="local-tool-path">{wrapPath(copy)}</dd></Fragment>)}
      {tool.role === 'detected' && <><dt>{t('Role')}</dt><dd>{t('Detected only; it does not run steps')}</dd></>}
      {tool.role === 'imports' && <><dt>{t('Role')}</dt><dd>{t('Imports a collection into a research, read-only')}</dd></>}
    </dl>}
    {tool.reason_code === 'not_responding' && <p className="local-tool-note is-callout">{t('Not responding: it did not answer its version check within 5 seconds.')}</p>}
    {tool.reason_code === 'not_runnable' && <p className="local-tool-note is-callout">{t('Found, but it did not run: its version check failed. Reinstall it, or remove the broken copy.')}</p>}
    {tool.reason_code === 'unsupported_install' && <p className="local-tool-note is-callout">{t('This copy is installed in a way DEIXIS cannot start on Windows. Install it again with its official Windows installer.')}</p>}
    {tool.installed && (tool.other_copies?.length ?? 0) > 0 && <p className="local-tool-note">{t('More than one copy is installed. DEIXIS uses the one shown under Path.')}</p>}
    {tool.kind === 'cli' && tool.role === 'detected' && <p className="local-tool-note">{t('DEIXIS only checks whether this tool is installed; it never uses it for research.')}</p>}
    {tool.kind === 'server' && tool.installed && (tool.running
      ? <>
        <p className="local-tool-note">{t('Running · {endpoint}', { endpoint: tool.endpoint ?? '' })}</p>
        {tool.models && tool.models.length > 0
          ? <ul className="local-tool-models">{tool.models.map(m => <li key={m.id}><span>{m.id}</span><span className="local-tool-model-meta">{m.size_bytes != null && formatBytes(m.size_bytes)}{m.embedding && <span className="status-chip is-configured">{t('Embedding')}</span>}</span></li>)}</ul>
          : <p className="local-tool-note">{t('No models found.')}</p>}
      </>
      : <p className="local-tool-note">{t(offerApp ? 'Only the command-line version is installed. Install the Ollama app to run it without a terminal.' : tool.id === 'ollama' ? 'Start it with `ollama serve`' : 'Open LM Studio and start its local server')}</p>)}
    {tool.kind === 'app' && tool.installed && <>
      <p className={`local-tool-note${tool.running && tool.local_api ? '' : ' is-callout'}`}>{!tool.running ? t('Not answering. Open Zotero and close any dialog it shows, then turn on Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”.') : tool.local_api ? t('Local API on · {endpoint}', { endpoint: tool.endpoint ?? '' }) : t('Running, but its local API is off. Turn on Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”.')}</p>
    </>}
    {offerInstall && (tool.install.available
      ? <>
        {!running && <div className="actions"><Button size="sm" onClick={() => setConfirmOpen(true)}>{t(offerApp ? 'Install the Ollama app' : 'Install')}</Button></div>}
        <ConfirmDialog open={confirmOpen} dark={dark} title={t('Install {name}?', { name })} description={t(tool.app_installed === false ? 'DEIXIS downloads the Ollama app from ollama.com (about 200 MB), copies it to Applications and opens it.' : 'DEIXIS installs it on this computer.')} confirmLabel={t('Install')} cancelLabel={t('Cancel')} busy={busy} onConfirm={install} onOpenChange={setConfirmOpen} />
      </>
      : <p className="local-tool-note">{installReasonText(tool.install.unavailable_reason, tool.install.manager)}<br /><a href={tool.install.url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>)}
    {tool.job && <>
      {running
        ? tool.job.total
          ? <InstallProgress percent={Math.min(100, Math.round((tool.job.completed ?? 0) / tool.job.total * 100))}
              label={tool.job.completed! < tool.job.total ? t('Downloading: {done} of {total} MB', { done: aboutMb(tool.job.completed ?? 0), total: aboutMb(tool.job.total) }) : t('Installing…')} />
          : <InstallProgress label={t('Installing…')} />
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
  const offerInstall = !ready && !running && reader.install.available
  return <div className="local-tool-details-panel tool-panel">
    <p className="tool-lead">{t('Marker reads the equations in your PDFs from the page image, so answers and tables get them as LaTeX instead of broken PDF text.')}</p>
    <ToolTraits items={[[<Laptop key="l" />, 'Runs on this computer'], [<ShieldCheck key="s" />, 'No file leaves it']]} />
    {offerInstall && <section className="tool-install">
      <HardDrive aria-hidden />
      <div><b>{t('About 4.4 GB of disk · {gb} GB free', { gb: reader.disk_free_gb })}</b><span>{t('DEIXIS installs it into its data folder.')}</span></div>
      <Button size="sm" onClick={() => setConfirm('install')}>{t('Install')}</Button>
    </section>}
    {!ready && !running && !reader.install.available && <p className="local-tool-note">{installReasonText(reader.install.unavailable_reason)}<br /><a href={reader.install.url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>}
    {reader.installed && <ReaderProgress reader={reader} />}
    <ToolCaveat>{t('About one Marker equation in fifty was misread in a test on three papers, and a misread equation looks correct. Equations that do not match the PDF’s own text are marked to check against the page.')}</ToolCaveat>
    <ToolFacts foot={ready && !running ? <ToolUpdateCheck tool="marker" /> : null}>
      <dt>{t('Package')}</dt><dd><code className="local-tool-code">{reader.package}</code></dd>
      <dt>{t('License')}</dt><dd>{t('Code GPL-3.0; the models have their own license')}</dd>
      {reader.size_bytes > 0 && <><dt>{t('Size on disk')}</dt><dd>{formatBytes(reader.size_bytes)}</dd></>}
      {!ready && !offerInstall && <><dt>{t('Needs')}</dt><dd>{t('About 4.4 GB of disk · {gb} GB free', { gb: reader.disk_free_gb })}</dd></>}
    </ToolFacts>
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
    <ConfirmDialog open={confirm === 'install'} dark={dark} title={t('Install the equation reader?')} description={t('This downloads Marker and its models (about 4.4 GB) into the DEIXIS data folder, which can take several minutes. Your stored PDFs are then read in the background, which can take hours for a large library.')} context={reader.path} confirmLabel={t('Install')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.installEquationReader)} onOpenChange={open => setConfirm(open ? 'install' : null)}>
      <p className="confirm-dialog-license">{t('License of {package}: the code is GPL-3.0-or-later. The model weights come with their own license, which limits commercial use.', { package: reader.package.replace('==', ' ') })}{' '}
        <a href={MARKER_LICENSE_URL} target="_blank" rel="noopener noreferrer">{t('Marker’s license terms on GitHub')}</a></p>
    </ConfirmDialog>
    <ConfirmDialog open={confirm === 'remove'} dark={dark} title={t('Remove the equation reader?')} description={t('Marker and its models are deleted. Equations already read stay in the stored text; new PDFs are no longer read.')} confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(api.removeEquationReader)} onOpenChange={open => setConfirm(open ? 'remove' : null)} />
  </div>
}

const MARKER_LICENSE_URL = 'https://github.com/datalab-to/marker'
const MATHPIX_PRIVACY_URL = 'https://mathpix.com/privacy-policy'

// Mathpix (D40): an online reader for numbered display equations, off until the person saves a key pair and turns it on.
// The pair is tested against Mathpix's usage API before it is saved; the switch asks first, with an upper bound of requests.
function MathpixDetails({ mathpix, keychain, dark, onChanged, onKeychainChanged }: { mathpix: Mathpix; keychain: Keychain; dark: boolean; onChanged: (next?: Mathpix) => void; onKeychainChanged: () => void }) {
  const [appId, setAppId] = useState('')
  const [appKey, setAppKey] = useState('')
  const [budget, setBudget] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [asking, setAsking] = useState(false)
  const [estimate, setEstimate] = useState<{ pdfs: number; upper_bound: number } | null>(null)
  const toast = useToast()
  const typed = !!(appId.trim() && appKey.trim())
  const fail = (e: Error) => setFormError(e.message)
  function savePair() {
    setBusy(true); setFormError('')
    api.saveMathpixPair(appId.trim(), appKey.trim()).then(result => {
      setAppId(''); setAppKey(''); onChanged(result.mathpix)
      toast(result.test.status === 'ok' ? 'success' : 'warning', result.test.status === 'ok'
        ? t('Key pair saved. Mathpix accepted it.') : t('Key pair saved, but Mathpix could not be reached to test it.'))
    }).catch((e: Error) => setFormError(e instanceof ApiError && e.code === 'credential_test_failed'
      ? t('The key pair was not saved. Mathpix did not accept it (HTTP {code}).', { code: String(e.details?.http_status ?? '?') }) : keychainError(e, keychain)))
      .finally(() => setBusy(false))
  }
  function test() {
    setBusy(true); setFormError('')
    api.testMathpixPair().then(result => {
      toast(result.status === 'ok' ? 'success' : 'warning', result.status === 'ok' ? t('Mathpix accepted the key pair.')
        : result.status === 'rejected' ? t('Mathpix did not accept the key pair (HTTP {code}).', { code: String(result.http_status ?? '?') })
        : t('Mathpix could not be reached to test the key pair.'))
      onChanged()
    }).catch(fail).finally(() => setBusy(false))
  }
  function remove() {
    setBusy(true); setFormError('')
    api.removeMathpixPair().then(result => { setAsking(false); onChanged(result.mathpix); toast('success', t('Key pair removed.')) })
      .catch((e: Error) => setFormError(keychainError(e, keychain))).finally(() => setBusy(false))
  }
  function askToTurnOn() {
    setBusy(true); setFormError('')
    api.mathpixEstimate().then(setEstimate).catch(fail).finally(() => setBusy(false))
  }
  function setSwitch(value: 'on' | 'off') {
    setBusy(true); setFormError('')
    api.saveMathpixSettings({ switch: value }).then(result => {
      setEstimate(null); onChanged(result)
      toast('success', value === 'on' ? t('Mathpix is on.') : t('Mathpix is off. Requests already sent finish; no new ones are sent.'))
    }).catch(fail).finally(() => setBusy(false))
  }
  function saveBudget() {
    const value = Number(budget)
    if (!Number.isInteger(value) || value < 0) { setFormError(t('Type a whole number of requests.')); return }
    setBusy(true); setFormError('')
    api.saveMathpixSettings({ monthly_budget: value }).then(result => { setBudget(null); onChanged(result); toast('success', t('Monthly budget saved.')) })
      .catch(fail).finally(() => setBusy(false))
  }
  const on = mathpix.switch === 'on'
  const pdfs = mathpix.pdfs
  const waiting = (pdfs.pending ?? 0) + (pdfs.reading ?? 0)
  const notUsed = (pdfs.no_candidates ?? 0) + (pdfs.none_placed ?? 0)
  const stopped = (pdfs.failed ?? 0) + (pdfs.keys_rejected ?? 0) + (pdfs.budget_reached ?? 0)
  const home = keyHome(keychain)
  const where = home.where
  return <div className="local-tool-details-panel tool-panel">
    <p className="tool-lead">{t('Mathpix reads the numbered equations in your PDFs from an image of the page. DEIXIS keeps an equation only when its letters, scripts and signs match the PDF’s own text.')}</p>
    <ToolTraits items={[[<Cloud key="c" />, 'Runs on Mathpix’s servers'], [<KeyRound key="k" />, 'Needs your own Mathpix key pair']]} />
    <Notice tone="attention"><p>{t('DEIXIS does not send the PDF or its extracted text. For each numbered equation it sends an image of the area it takes to be the equation; that area can hold nearby content.')} <a href={MATHPIX_PRIVACY_URL} target="_blank" rel="noopener noreferrer">{t('Mathpix privacy policy')}</a></p></Notice>
    {mathpix.marker_present && <p className="local-tool-note">{t('Marker is installed, so Marker reads the equations and Mathpix sends nothing.')}</p>}
    {mathpix.pair.keychain_unavailable && <Notice tone="attention"><p>{t('The system keychain did not answer, so your saved key pair was not used this time. It may be fine: restart DEIXIS once the keychain is unlocked.')}</p></Notice>}
    {mathpix.pair.keychain_pending && <Notice tone="attention"><p>{t('The system keychain has not answered the last change to this key pair yet. The pair shows its real state once it does; reopen Settings in a moment.')}</p></Notice>}
    {mathpix.pair.unreadable && <Notice tone="attention"><p>{t('The saved key pair could not be read. Save it again.')}</p></Notice>}
    {mathpix.keys_rejected && <Notice tone="attention"><p>{t('Mathpix did not accept the saved key pair. No request is sent until a new pair is saved.')}</p></Notice>}
    <form className="key-box" onSubmit={e => { e.preventDefault(); if (typed) savePair(); else if (mathpix.pair.configured) test() }}>
      <label className="lbl" htmlFor="mathpix-app-id">{t('App ID')}
        <input id="mathpix-app-id" className="field" type="text" spellCheck={false} value={appId} disabled={busy} autoComplete="off" data-1p-ignore data-lpignore="true" data-bwignore data-form-type="other"
          placeholder={mathpix.pair.app_id ?? t('Type your app ID')} onChange={e => { setAppId(e.target.value); setFormError('') }} />
      </label>
      <label className="lbl" htmlFor="mathpix-app-key">{t('App key')}
        <input id="mathpix-app-key" className="field" type="password" spellCheck={false} value={appKey} disabled={busy} autoComplete="new-password" data-1p-ignore data-lpignore="true" data-bwignore data-form-type="other"
          placeholder={mathpix.pair.configured ? `•••••••••••• ${where}` : t('Paste your key')} onChange={e => { setAppKey(e.target.value); setFormError('') }} />
      </label>
      <p className="foot-note">{home.note} {t('A new pair is tested with Mathpix’s usage API before it is saved. The test shows that Mathpix accepted the pair, not that the account has credit for reading images.')}</p>
      <KeyStore keychain={keychain} onChanged={onKeychainChanged} />
      {formError && <Notice tone="error"><p>{formError}</p></Notice>}
      <div className="acts">
        {(typed || mathpix.pair.configured) && <button type="submit" className="btn-pri" disabled={busy}>{busy ? <span className="spin" aria-hidden /> : typed ? <Save aria-hidden /> : <CircleCheck aria-hidden />}{t(typed ? 'Save and test' : 'Test')}</button>}
        {mathpix.pair.configured && !asking && <button type="button" className="ghost" disabled={busy} onClick={() => setAsking(true)}>{t('Remove key pair')}</button>}
      </div>
      {asking && <RemoveNotice busy={busy} onRemove={remove} onKeep={() => setAsking(false)} text={t('Remove the Mathpix key pair? No new request is sent; equations already read stay in the stored text.')} />}
    </form>
    <section className="tool-facts" aria-label={t('Mathpix use')}>
      <dl>
        <dt>{t('Reading')}</dt><dd>{t(on ? 'On' : 'Off')}{' '}
          {on ? <button type="button" className="ghost" disabled={busy} onClick={() => setSwitch('off')}>{t('Turn off')}</button>
            : <button type="button" className="ghost" disabled={busy || !mathpix.pair.configured || mathpix.keys_rejected} onClick={askToTurnOn}>{t('Turn on…')}</button>}</dd>
        <dt>{t('This month')}</dt><dd>{t('{n} of {budget} requests · at most {limit} per PDF', { n: mathpix.month_requests, budget: mathpix.monthly_budget, limit: mathpix.per_pdf_limit })}</dd>
        <dt><label htmlFor="mathpix-budget">{t('Requests per month')}</label></dt><dd>
          <input id="mathpix-budget" className="field mathpix-budget" type="number" min={0} step={1} inputMode="numeric" value={budget ?? String(mathpix.monthly_budget)} disabled={busy} onChange={e => { setBudget(e.target.value); setFormError('') }} />
          {budget !== null && <button type="button" className="ghost" disabled={busy} onClick={saveBudget}>{t('Save')}</button>}
        </dd>
        <dt>{t('PDFs')}</dt><dd>{t('{read} read · {waiting} waiting · {none} without a usable equation · {stopped} stopped', { read: pdfs.read ?? 0, waiting, none: notUsed, stopped })}</dd>
      </dl>
    </section>
    <ToolCaveat>{t('DEIXIS has not measured how often Mathpix misreads an equation. An equation whose letters, scripts or signs differ from the PDF’s text is not used, but a misread that keeps all of them, such as a wrong digit, can pass. Check equations against the page.')}</ToolCaveat>
    <ConfirmDialog open={estimate !== null} dark={dark} title={t('Turn on Mathpix?')}
      description={estimate ? t('{pdfs} PDFs in the library have numbered equations Mathpix would read now: at most {n} requests, within this month’s budget. New PDFs are read as they arrive. Turning it off stops new requests; requests already sent finish.', { pdfs: estimate.pdfs, n: estimate.upper_bound }) : ''}
      confirmLabel={t('Turn on')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => setSwitch('on')} onOpenChange={open => { if (!open) setEstimate(null) }} />
  </div>
}

// An indeterminate bar: the installers report the step they are on, not a fraction.
function InstallProgress({ label, percent }: { label: string; percent?: number }) {
  return <div className="install-progress" role="status">
    <span className="install-progress-label"><LoaderCircle size={14} className="chat-spin" aria-hidden />{label}</span>
    <div className={`install-progress-bar${percent != null ? ' is-determinate' : ''}`} aria-hidden><span style={percent != null ? { width: `${percent}%` } : undefined} /></div>
  </div>
}

// A local model server not answering: install it, on macOS as the app from its site (Homebrew's Ollama CLI alone starts no
// server). The job is the tool's install job, polled with the other tools; its bytes give the bar while the disk image
// downloads. LM Studio installed but with its server off gets a button that runs `lms server start`.
function LocalAppInstall({ tool, dark, onChanged, onDone }: { tool: LocalTool; dark: boolean; onChanged: () => Promise<void>; onDone: () => void }) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState(false)
  const toast = useToast()
  const job = tool.job
  const status = job?.status
  const previous = useRef(status)
  useEffect(() => {
    if (previous.current === 'running' && status === 'succeeded') onDone()
    previous.current = status
  }, [status, onDone])
  const app = tool.app_installed === false
  const name = tool.name || localToolNames[tool.id] || tool.id
  function startServer() {
    setStarting(true)
    api.startLmStudioServer().then(() => { onDone(); return onChanged() }).catch((e: Error) => toast('error', e.message)).finally(() => setStarting(false))
  }
  if (tool.id === 'lm_studio' && tool.installed && !app && status !== 'running') return <div className="server-pull">
    <p className="local-tool-note">{t('LM Studio is installed, but its local server is off.')}</p>
    <div className="actions"><Button size="sm" onClick={startServer} disabled={starting}><Server size={14} aria-hidden />{t(starting ? 'Starting…' : 'Start the server')}</Button></div>
  </div>
  if (!tool.install.available || (tool.installed && !app && status !== 'running')) return null
  function install() {
    setBusy(true)
    api.installLocalTool(tool.id).then(() => { setConfirmOpen(false); return onChanged() }).catch((e: Error) => toast('error', installError(e, tool))).finally(() => setBusy(false))
  }
  return <div className="server-pull">
    {status === 'running'
      ? job!.total
        ? <InstallProgress percent={Math.min(100, Math.round((job!.completed ?? 0) / job!.total * 100))}
            label={(job!.completed ?? 0) < job!.total ? t('Downloading: {done} of {total} MB', { done: aboutMb(job!.completed ?? 0), total: aboutMb(job!.total) }) : t('Installing…')} />
        : <InstallProgress label={t('Installing…')} />
      : <>
        {status === 'failed' && <>
          <p className="local-tool-error">{t('Install failed.')}</p>
          {errorLines(job!.output).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
        </>}
        {tool.installed && app && tool.id === 'ollama' && <p className="local-tool-note">{t('Only the command-line version is installed. Install the Ollama app to run it without a terminal.')}</p>}
        <div className="actions"><Button size="sm" onClick={() => setConfirmOpen(true)}><Download size={14} aria-hidden />{app ? t('Install the {name} app', { name }) : t('Install')}</Button></div>
      </>}
    <ConfirmDialog open={confirmOpen} dark={dark} title={t('Install {name}?', { name })}
      description={!app ? t('DEIXIS installs it on this computer.') : tool.id === 'ollama'
        ? t('DEIXIS downloads the Ollama app from ollama.com (about 200 MB), copies it to Applications and opens it.')
        : t('DEIXIS downloads the LM Studio app from lmstudio.ai (about 500 MB), copies it to Applications and opens it. Start its server from this card afterwards.')}
      confirmLabel={t('Install')} cancelLabel={t('Cancel')} busy={busy} onConfirm={install} onOpenChange={setConfirmOpen} />
  </div>
}

// A local server card's models (Ollama, LM Studio): what is installed (each can be removed), a short list of suggested models and a name box for
// any other library model. One download runs at a time; Ollama reports bytes per layer, summed into one bar.
function LocalModels({ tool, dark, memoryGb, onChanged, onDone }: { tool: LocalTool; dark: boolean; memoryGb: number | null; onChanged: () => Promise<void>; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [removing, setRemoving] = useState<string | null>(null)
  const toast = useToast()
  const pull = tool.pull
  const status = pull?.status
  const pulling = status === 'running'
  const previous = useRef(status)
  useEffect(() => {
    if (previous.current === 'running' && status === 'succeeded') onDone()
    previous.current = status
  }, [status, onDone])
  // Checked once when the card opens and again after each download; a check that gets no answer shows nothing.
  const [updates, setUpdates] = useState<OllamaUpdates | null>(null)
  // The app's own update (Homebrew's `brew upgrade` or the newer macOS app copied over it) runs as the tool's job.
  const job = tool.job?.kind === 'update' ? tool.job : null
  const updating = job?.status === 'running'
  const checkedAfter = `${pull?.finished_at ?? ''}|${job?.finished_at ?? ''}`
  useEffect(() => {
    let live = true
    const leaving = new AbortController()
    api.localToolUpdates(tool.id === 'lm_studio' ? 'lm_studio' : 'ollama', leaving.signal).then(u => { if (live) setUpdates(u) }, () => { if (live) setUpdates(null) })
    return () => { live = false; leaving.abort() }
  }, [checkedAfter, tool.id])
  const lms = tool.id === 'lm_studio'
  const product = lms ? 'LM Studio' : 'Ollama'
  // The fixed list shows at once; the catalog's current models (read by the server at most once a day) replace it.
  const [catalog, setCatalog] = useState<{ models: NonNullable<LocalTool['suggested']>; source: 'catalog' | 'fixed' } | null>(null)
  useEffect(() => {
    let live = true
    const leaving = new AbortController()
    api.localToolSuggested(lms ? 'lm_studio' : 'ollama', leaving.signal).then(c => { if (live) setCatalog(c) }, () => { if (live) setCatalog(null) })
    return () => { live = false; leaving.abort() }
  }, [lms])
  // Embedding models are chosen under Search & ranking; these lists are the research models.
  const installed = (tool.models ?? []).filter(m => !m.embedding)
  // Ollama names carry a tag (":latest" when none is given); LM Studio lists a catalog model by its own key or file name.
  const full = (id: string) => lms ? id.toLowerCase().split('/').pop()! : id.includes(':') ? id : `${id}:latest`
  const have = new Set((tool.models ?? []).map(m => full(m.id)))
  const suggested = (catalog?.models ?? tool.suggested ?? []).filter(s => !have.has(full(s.id)))
  const research = suggested.filter(s => s.purpose === 'research')
  function updateApp() {
    setBusy(true)
    api.updateLocalTool(lms ? 'lm_studio' : 'ollama').then(onChanged).catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }
  function start(model: string) {
    setBusy(true)
    const pulled = lms ? api.pullLmStudioModel(model) : api.pullOllamaModel(model)
    pulled.then(() => { setName(''); return onChanged() }).catch((e: Error) => toast('error', e instanceof ApiError ? toolActionError(e) : e.message)).finally(() => setBusy(false))
  }
  const [cancelling, setCancelling] = useState(false)
  function cancelPull() {
    setCancelling(true)
    api.cancelOllamaPull().then(onChanged).catch((e: Error) => toast('error', e.message)).finally(() => setCancelling(false))
  }
  function remove() {
    if (!removing) return
    setBusy(true)
    api.deleteOllamaModel(removing).then(() => { setRemoving(null); return onChanged() }).catch((e: Error) => toast('error', e instanceof ApiError ? toolActionError(e) : e.message)).finally(() => setBusy(false))
  }
  return <>
    {updating
      ? <InstallProgress percent={job!.total ? Math.min(100, Math.round((job!.completed ?? 0) / job!.total * 100)) : undefined}
          label={job!.total && (job!.completed ?? 0) < job!.total
            ? t('Downloading {name}: {done} of {total} MB', { name: product, done: aboutMb(job!.completed ?? 0), total: aboutMb(job!.total) })
            : t('Updating {name}…', { name: product })} />
      : updates?.update_available && (updates.installed_with ? <div className="local-tool-note ollama-update" role="status">
        <span><RefreshCw size={15} aria-hidden />{t('{name} {latest} is available (this computer has {version}).', { name: product, latest: updates.latest ?? '', version: updates.version ?? '' })}</span>
        <Button size="sm" disabled={busy || pulling} onClick={updateApp}><RefreshCw size={14} aria-hidden />{t('Update')}</Button>
      </div>
      : <p className="local-tool-note ollama-update" role="status">
        {t('{name} {latest} is available (this computer has {version}).', { name: product, latest: updates.latest ?? '', version: updates.version ?? '' })}{' '}
        <a href={lms ? 'https://lmstudio.ai/download' : 'https://ollama.com/download'} target="_blank" rel="noopener noreferrer">{lms ? 'lmstudio.ai/download' : 'ollama.com/download'}</a>
      </p>)}
    {job?.status === 'failed' && <>
      <p className="local-tool-error">{t('The update of {name} did not finish.', { name: product })}</p>
      {errorLines(job.output).map((line, k) => <p key={k} className="local-tool-error">{line}</p>)}
    </>}
    {pulling && <div className="server-pull">
      <InstallProgress percent={pull!.total ? Math.min(100, Math.round(pull!.completed / pull!.total * 100)) : undefined} label={pull!.total
        ? t('Downloading {model}: {done} of {total} MB', { model: pull!.model, done: aboutMb(pull!.completed), total: aboutMb(pull!.total) })
        : t('Preparing the download of {model}…', { model: pull!.model })} />
      <div className="actions"><Button variant="outline" size="sm" className="is-destructive" onClick={cancelPull} disabled={cancelling}>{t(cancelling ? 'Cancelling…' : 'Cancel download')}</Button></div>
    </div>}
    {status === 'cancelled' && <p className="local-tool-note">{t('The download of {model} was cancelled.', { model: pull!.model })}</p>}
    {status === 'succeeded' && <p className="local-tool-note">{t('{model} is downloaded.', { model: pull!.model })}</p>}
    {status === 'failed' && <>
      <p className="local-tool-error">{t('The download of {model} did not finish.', { model: pull!.model })}</p>
      {errorLines(pull!.output).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
    </>}

    <h3 className="source-section">{t('Installed models')}{installed.length > 0 && <span className="ollama-count">{installed.length}</span>}</h3>
    {installed.length > 0
      ? <ul className="local-tool-models ollama-models is-installed">{installed.map(m => <li key={m.id}>
        <span className="ollama-model-ico" aria-hidden><Cpu size={14} /></span>
        <span className="ollama-model-name" title={m.id}>{m.id}</span>
        <span className="local-tool-model-meta">
          {m.size_bytes != null && <span className="ollama-size">{formatBytes(m.size_bytes)}</span>}
          {updates?.models[m.id] && <button type="button" className="ghost" title={t('ollama.com has a newer version of this model')} disabled={busy || pulling} onClick={() => start(m.id)}><RefreshCw size={14} aria-hidden />{t('Update')}</button>}
          {!lms && <button type="button" className="ghost icon-only" aria-label={t('Remove {model}', { model: m.id })} title={t('Remove')} disabled={busy} onClick={() => setRemoving(m.id)}><Trash2 size={14} aria-hidden /></button>}
        </span>
      </li>)}</ul>
      : <div className="ollama-empty">
        <span className="ollama-model-ico" aria-hidden><Cpu size={14} /></span>
        <p><b>{t('No language model is installed.')}</b>{research.length > 0 && <span>{t('Download one of the suggested models below to use it in research steps.')}</span>}</p>
      </div>}

    {research.length > 0 && <>
      <h3 className="source-section">{t('Suggested models')}</h3>
      {catalog?.source === 'catalog' && <p className="foot-note">{t('New models from {site}, each in the largest size that fits this computer’s memory.', { site: lms ? 'lmstudio.ai' : 'ollama.com' })}</p>}
      <ul className="ollama-cards">{research.map(s => {
        // A model needs about its download size plus a few GB of memory to run; one that does not fit is shown faded.
        const need = s.memory_gb ?? Math.ceil(((s.size_bytes ?? 0) / 1e9 + 4) / 4) * 4
        const tight = memoryGb != null && memoryGb < need
        // The catalog names a model "family · size"; the size goes in its own badge.
        const [title, params] = s.name.split(' · ')
        return <li key={s.id} className={`ollama-card${tight ? ' is-tight' : ''}`}>
          <div className="ollama-card-head"><b>{title}</b>{params && <span className="ollama-card-param">{params}</span>}</div>
          <small title={s.id}>{s.maker && `${s.maker} · `}<code>{s.id}</code></small>
          <div className="ollama-card-foot">
            <span className="ollama-card-size" title={tight ? t('More than this computer’s {memory} GB of memory', { memory: memoryGb! }) : undefined}>{tight ? <TriangleAlert size={12} aria-hidden /> : <MemoryStick size={12} aria-hidden />}{s.size_bytes != null ? t('{size} · {need} GB memory', { size: formatBytes(s.size_bytes), need }) : t('{need} GB memory', { need })}</span>
            {memoryGb != null && <span className="ollama-card-meter" aria-hidden><span style={{ width: `${Math.min(100, need / memoryGb * 100)}%` }} /></span>}
            <button type="button" className="ghost" disabled={busy || pulling} onClick={() => start(s.id)}><Download size={14} aria-hidden />{t('Download')}</button>
          </div>
        </li>
      })}</ul>
    </>}
    <details className="ollama-other">
      <summary>{t('Another model')}</summary>
      <form className="ollama-pull-form" onSubmit={e => { e.preventDefault(); if (name.trim()) start(name.trim()) }}>
        <span className="ollama-pull-row">
          <input className="field mono" aria-label={t('Another model')} value={name} onChange={e => setName(e.target.value)} placeholder={lms ? 'qwen/qwen3.5-9b' : 'qwen3.5:9b'} spellCheck={false} autoCapitalize="off" autoComplete="off" />
          <button type="submit" className="ghost" disabled={busy || pulling || !name.trim()}><Download size={14} aria-hidden />{t('Download')}</button>
        </span>
        <p className="foot-note">{t('Names are listed at')} {lms
          ? <a href="https://lmstudio.ai/models" target="_blank" rel="noopener noreferrer">lmstudio.ai/models</a>
          : <a href="https://ollama.com/library" target="_blank" rel="noopener noreferrer">ollama.com/library</a>}.</p>
      </form>
    </details>

    <ConfirmDialog open={removing !== null} dark={dark} title={t('Remove {model}?', { model: removing ?? '' })} description={t('Ollama deletes it from this computer. You can download it again later.')}
      confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={remove} onOpenChange={open => { if (!open) setRemoving(null) }} />
  </>
}

// The release check for a PDF tool, sent when its panel opens; it answers in one quiet line. Marker and PyMuPDF are
// pinned by DEIXIS, so a newer release arrives with a DEIXIS update. A failed check shows nothing.
function useToolUpdate(tool: ToolUpdate['tool'], key: unknown = null) {
  const [result, setResult] = useState<ToolUpdate | null>(null)
  useEffect(() => {
    let live = true
    const leaving = new AbortController()
    api.toolUpdate(tool, leaving.signal).then(r => { if (live) setResult(r) }, () => { if (live) setResult(null) })
    return () => { live = false; leaving.abort() }
  }, [tool, key])
  return result?.error || !result?.latest ? null : result
}

// The three PDF tools' sheets share one layout: what the tool does, where it runs, how far its output can be trusted,
// then its facts with the release check as their last row.
function ToolTraits({ items }: { items: [ReactNode, string][] }) {
  return <ul className="tool-traits">{items.map(([icon, label]) => <li key={label}>{icon}{t(label)}</li>)}</ul>
}

function ToolCaveat({ children }: { children: ReactNode }) {
  return <section className="tool-caveat"><Info aria-hidden /><div><h4>{t('How accurate it is')}</h4><p>{children}</p></div></section>
}

function ToolFacts({ children, foot }: { children: ReactNode; foot?: ReactNode }) {
  return <section className="tool-facts" aria-label={t('Details')}>
    <dl>{children}</dl>
    {foot}
  </section>
}

function ToolUpdateCheck({ tool }: { tool: 'marker' | 'pymupdf' }) {
  const result = useToolUpdate(tool)
  if (!result?.installed) return null
  const stale = result.tested && result.installed !== result.tested
  // Marker stays pinned to its tested version, so a newer release on PyPI is not shown.
  const hideNewer = result.update_available && tool === 'marker'
  return <>
    {!hideNewer && <p className={`tool-facts-foot${result.update_available ? '' : ' is-ok'}`} role="status">{result.update_available
      ? <><Info aria-hidden />{t('Version {latest} comes with the next DEIXIS update.', { latest: result.latest ?? '' })}</>
      : <><CircleCheck aria-hidden />{t('Up to date.')}</>}</p>}
    {stale && <p className="tool-facts-foot">{t('The installed Marker is {installed}, not {tested}. Remove it and install it again to get the tested version.', { installed: result.installed, tested: result.tested ?? '' })}</p>}
  </>
}

// PyMuPDF reads the text layer of every PDF; it comes with DEIXIS, so there is nothing to install.
function PdfReaderDetails({ reader }: { reader: PdfReader }) {
  return <div className="local-tool-details-panel tool-panel">
    <p className="tool-lead">{t('PyMuPDF reads the text, page numbers and layout of every PDF you add or DEIXIS fetches.')}</p>
    <ToolTraits items={[[<Package key="p" />, 'Comes with DEIXIS'], [<Laptop key="l" />, 'Runs on this computer'], [<ShieldCheck key="s" />, 'No file leaves it']]} />
    <ToolFacts foot={<ToolUpdateCheck tool="pymupdf" />}>
      <dt>{t('Version')}</dt><dd>{reader.version}</dd>
      <dt>{t('MuPDF')}</dt><dd>{reader.mupdf_version}</dd>
      <dt>{t('License')}</dt><dd>AGPL-3.0</dd>
    </ToolFacts>
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
    api.installOcr().then(() => onChanged()).catch((e: Error) => toast('error', e instanceof ApiError ? toolActionError(e, 'brew') : e.message)).finally(() => setBusy(false))
  }
  const phase = { preparing: 'Preparing…', downloading: 'Downloading…', installing: 'Installing…' }[job?.phase ?? 'preparing']
  const upToDate = ready && update && !update.update_available
  const canUpdate = ready && !running && update?.update_available && tool.can_install
  return <div className="local-tool-details-panel tool-panel">
    <p className="tool-lead">{t('Tesseract reads scanned PDF pages that have no selectable text when you choose Read with OCR on a source.')}</p>
    <ToolTraits items={[...(tool.bundled ? [[<Package key="p" />, 'Comes with DEIXIS'] as [ReactNode, string]] : []), [<Laptop key="l" />, 'Runs on this computer'], [<ShieldCheck key="s" />, 'No file leaves it'], [<FileLock key="f" />, 'The PDF is not changed']]} />
    {running
      ? job.phase === 'downloading' && job.packages_total && (job.packages_done ?? 0) < job.packages_total
        ? <InstallProgress label={t('Downloading: {done} of {total} packages', { done: job.packages_done ?? 0, total: job.packages_total })}
          percent={Math.round(100 * (job.packages_done ?? 0) / job.packages_total)} />
        : <InstallProgress label={t(phase)} />
      : !ready && tool.bundled ? <p className="local-tool-note is-callout">{t('Tesseract comes with DEIXIS but could not be run. Reinstall DEIXIS.')}</p>
      : !ready && (tool.can_install
        ? <section className="tool-install">
          <ScanText aria-hidden />
          <div><b>{t('Installed with Homebrew')}</b><span>{t('DEIXIS runs the install command for you.')}</span></div>
          <Button size="sm" onClick={install} disabled={busy}>{t('Install')}</Button>
        </section>
        : tool.install_manager === 'brew'
          ? <p className="local-tool-note">{t('Installing Tesseract needs Homebrew.')} <a href={tool.install_url} target="_blank" rel="noopener noreferrer">brew.sh</a></p>
          : <p className="local-tool-note">{t('Tesseract is installed from its download page. Install it there, then open this panel again.')}<br /><a href={tool.install_url} target="_blank" rel="noopener noreferrer">{t('Installation instructions')}</a></p>)}
    {job?.status === 'failed' && <>
      <p className="local-tool-error">{t('Install failed.')}</p>
      {job.output && <details className="local-tool-details"><summary>{t('Show full output')}</summary><pre className="local-tool-output">{job.output}</pre></details>}
    </>}
    <ToolCaveat>{t('Text read by OCR is labelled wherever it is quoted. In a test on four scanned articles, 0.2–1.5% of characters were misread and equations were unusable, so check numbers and equations against the page.')}</ToolCaveat>
    {tool.version && <ToolFacts foot={tool.bundled
      ? <p className="tool-facts-foot is-ok" role="status"><CircleCheck aria-hidden />{t('Updated together with DEIXIS.')}</p>
      : canUpdate ? <div className="tool-facts-foot is-update"><span><Info aria-hidden />{t('Version {latest} is available.', { latest: update.latest ?? '' })}</span><Button size="sm" onClick={install} disabled={busy}>{t('Update')}</Button></div>
      : upToDate ? <p className="tool-facts-foot is-ok" role="status"><CircleCheck aria-hidden />{t('Up to date.')}</p> : null}>
      <dt>{t('Version')}</dt><dd>{tool.version}</dd>
      {tool.path && <><dt>{t('Path')}</dt><dd className="local-tool-path">{wrapPath(tool.path)}</dd></>}
      {tool.languages.length > 0 && <><dt>{t('Languages')}</dt><dd>{ocrLanguagesText(tool.languages)}</dd></>}
      {tool.missing_languages.length > 0 && <><dt>{t('Missing')}</dt><dd>{ocrLanguagesText(tool.missing_languages)}</dd></>}
    </ToolFacts>}
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

// The built-in models (llama.cpp, a catalog of GGUF files): one card per catalog model of a kind, laid out like the
// Ollama sheet's suggested models, and one sheet per model with its files (download, progress, check, remove) and the
// button that chooses it. The recommendation is the backend's starting rule from this computer's memory, not measured.
const builtinSteps: Record<string, string> = {
  runtime: 'Downloading llama.cpp…', model_file: 'Downloading the model file…', start_check: 'Checking that the model starts and answers…',
}
const builtinStateText: Record<string, string> = {
  not_installed: 'Not downloaded', installing: 'Downloading', installing_elsewhere: 'Downloading', ready: 'Ready', failed: 'Download failed',
  files_do_not_match: 'Files do not match', not_checked: 'Not checked', runtime_missing: 'llama.cpp is missing', removing: 'Being removed',
  remove_failed: 'Removal did not finish', unsupported_platform: 'Not available on this platform',
}
const aboutMb = (bytes: number) => Math.round(bytes / 1e6)
// A translated template whose {name} placeholders are identifiers (model IDs, package names), shown in mono.
const withCode = (template: string, vars: Record<string, string>): ReactNode =>
  template.split(/\{(\w+)\}/).map((part, i) => i % 2 ? <code key={i} className="model-id">{vars[part] ?? part}</code> : part)
const lastLines = (output: string) => output.split('\n').map(line => line.trim()).filter(Boolean).slice(-3)
const builtinProgress = (m: BuiltinModel) => {
  const job = m.job
  return job?.bytes_total ? Math.min(100, Math.round((job.bytes_done ?? 0) / job.bytes_total * 100)) : undefined
}
// The card's pill: "In use" only when the saved provider and model are both this one.
function builtinPill(m: BuiltinModel, inUse: boolean): [Tone, string] {
  if (m.state === 'installing' && m.job?.bytes_total) return ['no', t('Downloading {done} of {total} MB', { done: aboutMb(m.job.bytes_done ?? 0), total: aboutMb(m.job.bytes_total) })]
  if (m.state === 'ready') return ['ok', t(inUse ? 'In use' : 'Ready')]
  if (m.state === 'failed' || m.state === 'files_do_not_match' || m.state === 'remove_failed' || m.state === 'runtime_missing') return ['warn', t(builtinStateText[m.state])]
  return ['no', t(builtinStateText[m.state] ?? 'Not downloaded')]
}

function BuiltinCatalog({ builtin, kind, inUse, onOpen }: { builtin: BuiltinModels; kind: BuiltinModel['kind']; inUse: string | null; onOpen: (id: string) => void }) {
  const memory = builtin.machine.memory_gb
  return <ul className="ollama-cards builtin-cards" data-kind={kind}>{builtin.models.filter(m => m.kind === kind).map(m => {
    const [tone, pill] = builtinPill(m, m.id === inUse)
    const percent = m.state === 'installing' ? builtinProgress(m) : undefined
    return <li key={m.id}>
      <button type="button" className={`ollama-card builtin-card${m.may_not_fit ? ' is-tight' : ''}${m.id === inUse ? ' on' : ''}`} onClick={() => onOpen(m.id)}>
        <span className="ollama-card-head"><b><code className="model-id">{m.name}</code></b><span className="ollama-card-param">{m.params}</span></span>
        <small title={m.file}>{m.maker} · <code className="model-id">{m.file}</code></small>
        {(m.recommended || !m.official) && <span className="builtin-tags">
          {m.recommended && <span className="st rec" title={t('Picked from this computer’s memory by a starting rule, not measured.')}>{t('Recommended for this computer')}</span>}
          {!m.official && <span className="builtin-tag">{t('Community conversion')}</span>}
        </span>}
        <span className="ollama-card-foot">
          <span className="ollama-card-size">{m.may_not_fit ? <TriangleAlert size={12} aria-hidden /> : <MemoryStick size={12} aria-hidden />}{t('{size} · about {need} GB memory', { size: formatBytes(m.bytes), need: m.memory_gb })}</span>
          {memory != null && <span className="ollama-card-meter" aria-hidden><span style={{ width: `${Math.min(100, m.memory_gb / memory * 100)}%` }} /></span>}
          {m.may_not_fit && <span className="builtin-fit">{t('May not fit in this computer’s {memory} GB of memory', { memory: memory ?? '' })}</span>}
          {percent != null && <span className="install-progress-bar is-determinate" aria-hidden><span style={{ width: `${percent}%` }} /></span>}
          <span className={`st ${tone}`}>{pill}</span>
        </span>
      </button>
    </li>
  })}</ul>
}

// A model's sheet: what it is, its files and the section that chooses it (given by the semantic search or reranking section).
function BuiltinModelSheet({ builtin, model, dark, use, onClose, onChanged }: {
  builtin: BuiltinModels; model: BuiltinModel | null; dark: boolean; use: ReactNode; onClose: () => void; onChanged: () => Promise<void>
}) {
  return <Sheet open={!!model} onOpenChange={next => { if (!next) onClose() }}>
    <SheetContent className={`detail-sheet connection-sheet ${dark ? 'dark' : ''}`}>
      {model && <>
        <SheetHeader className="sheet-head">
          <span className="sheet-mark" aria-hidden>{settingsIcon('builtin')}</span>
          <div className="sheet-head-text">
            <SheetTitle>{model.name}</SheetTitle>
            <SheetDescription>{t(model.kind === 'embedding' ? 'Semantic search' : 'Reranking')}</SheetDescription>
          </div>
        </SheetHeader>
        <div className="connection-body mk pad detail">
          <p className="foot-note is-ink">{model.kind === 'embedding'
            ? (model.english_query_required
              ? withCode(t('{model} · reads English; for a question in another language it asks for one English sentence'), { model: model.name })
              : withCode(t('{model} · reads questions in many languages'), { model: model.name }))
            : withCode(t('{model} · runs on this computer; no text leaves it'), { model: model.name })}</p>
          <BuiltinModelFiles builtin={builtin} model={model} dark={dark} onChanged={onChanged} />
          {use}
        </div>
      </>}
    </SheetContent>
  </Sheet>
}

function BuiltinModelFiles({ builtin, model: m, dark, onChanged }: { builtin: BuiltinModels; model: BuiltinModel; dark: boolean; onChanged: () => Promise<void> }) {
  const [confirm, setConfirm] = useState<'install' | 'remove' | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  function run(action: () => Promise<unknown>) {
    setBusy(true)
    action().then(() => { setConfirm(null); return onChanged() }).catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }
  const job = m.job
  const state = m.state
  const running = state === 'installing'
  const installed = m.bytes_on_disk > 0 || ['ready', 'not_checked', 'files_do_not_match', 'runtime_missing'].includes(state)
  const otherRunning = builtin.models.some(o => o.id !== m.id && (o.state === 'installing' || o.state === 'installing_elsewhere'))
  const canDownload = ['not_installed', 'failed', 'files_do_not_match', 'runtime_missing'].includes(state)
  const runtime = builtin.runtime
  const checked = m.last_full_check ? new Date(m.last_full_check.at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) : null
  const stepName = job ? t(builtinSteps[job.step_name ?? ''] ?? '') : ''
  const [tone, pill] = builtinPill(m, false)
  const runtimeExtra = !runtime.installed && runtime.download_bytes ? runtime.download_bytes : 0
  const memory = builtin.machine.memory_gb
  if (state === 'unsupported_platform') return <section className="way semantic-builtin" aria-label={t('Model files')}>
    <div className="way-head"><h3>{t('Model files')}</h3><span className="st no">{t(builtinStateText[state])}</span></div>
    <p className="way-desc">{t('The built-in models are not available on this platform yet.')}</p>
  </section>
  return <section className={`way semantic-builtin ${state === 'ready' ? 'is-on' : ''}`} aria-label={t('Model files')}>
    <div className="way-head"><h3>{t('Model files')}</h3><span className={`st ${tone}`}>{pill}</span></div>
    {m.recommended && <p className="way-desc builtin-rec"><span className="st rec">{t('Recommended for this computer')}</span> {t('Picked from this computer’s memory by a starting rule, not measured.')}</p>}
    {state === 'ready' && <p className="way-desc">{checked ? t('Files checked {time}, at install and with Check files.', { time: checked }) : t('Files checked at install and with Check files.')}</p>}
    {state === 'not_checked' && <p className="way-desc">{t('The file is in place but has not been checked yet. Check files reads it in full.')}</p>}
    {state === 'files_do_not_match' && <p className="local-tool-error">{t('The model file does not match its pinned copy, so the model is not used. Download it again.')}</p>}
    {state === 'runtime_missing' && <p className="local-tool-error">{t('llama.cpp, which runs the model, is missing or changed. Download again to put it back; the model file is kept if it is whole.')}</p>}
    {state === 'installing_elsewhere' && <p className="way-desc">{t('Another running copy of DEIXIS is downloading it.')}</p>}
    {state === 'removing' && <p className="way-desc">{t('Being removed…')}</p>}
    {state === 'remove_failed' && <>
      <p className="local-tool-error">{t('Removal did not finish: some files could not be deleted.')}</p>
      {(job?.output ?? '').split('\n').filter(Boolean).slice(0, 4).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
    </>}
    {running && job && <InstallProgress percent={builtinProgress(m)} label={t('Step {step} of {steps}: {what}', { step: job.step, steps: job.steps, what: stepName })
      + (job.bytes_total && job.step_name !== 'start_check' ? ` ${t('{done} of {total} MB', { done: aboutMb(job.bytes_done ?? 0), total: aboutMb(job.bytes_total) })}` : '')} />}
    {state === 'failed' && job && <>
      <p className="local-tool-error">{t('Download failed at step {step} of {steps}: {what}', { step: job.step, steps: job.steps, what: stepName })}</p>
      {lastLines(job.output).map((line, i) => <p key={i} className="local-tool-error">{line}</p>)}
    </>}
    {!running && job?.status === 'cancelled' && state !== 'ready' && <p className="way-desc">{t('Download cancelled.')}</p>}
    {job?.output && (state === 'failed' || running) && <details className="local-tool-details"><summary>{t('Show full output')}</summary><pre className="local-tool-output">{job.output}</pre></details>}
    <dl className="builtin-facts">
      <dt>{t('Size')}</dt><dd>{formatBytes(m.bytes)}</dd>
      <dt>{t('Memory')}</dt><dd>{t('about {need} GB (estimated)', { need: m.memory_gb })}{memory != null && <> · {t('this computer has {memory} GB', { memory })}</>}{m.may_not_fit && <span className="builtin-fit"><TriangleAlert size={12} aria-hidden />{t('May not fit in this computer’s {memory} GB of memory', { memory: memory ?? '' })}</span>}</dd>
      <dt>{t('File')}</dt><dd><code className="model-id">{m.file}</code></dd>
      <dt>{t('Source')}</dt><dd><a href={`https://huggingface.co/${m.repo}`} target="_blank" rel="noopener noreferrer">{m.repo}</a>{!m.official && <> · {t('Community conversion')}</>}</dd>
      <dt>{t('License')}</dt><dd>{m.license}</dd>
      <dt>{t('Runtime')}</dt><dd>{withCode(t('llama.cpp {tag}'), { tag: runtime.tag })}{runtime.installed ? '' : runtime.download_bytes ? ` · ${t('{size}, downloaded with the first model', { size: formatBytes(runtime.download_bytes) })}` : ''}</dd>
    </dl>
    {canDownload && <div className="actions"><button type="button" className="btn-pri" disabled={busy || otherRunning} aria-describedby={otherRunning ? `builtin-wait-${m.id}` : undefined} onClick={() => setConfirm('install')}><Download aria-hidden />{t(state === 'not_installed' ? 'Download' : 'Download again')}</button>
      {installed && <button type="button" className="ghost" disabled={busy} onClick={() => setConfirm('remove')}>{t('Remove')}</button>}</div>}
    {canDownload && otherRunning && <p className="way-desc" id={`builtin-wait-${m.id}`}>{t('Another built-in model is being downloaded; one download runs at a time.')}</p>}
    {running && <div className="actions"><button type="button" className="ghost" disabled={busy} onClick={() => run(api.cancelBuiltinModel)}>{t('Cancel download')}</button></div>}
    {(state === 'ready' || state === 'not_checked') && <div className="actions"><button type="button" className="btn-pri" disabled={busy} onClick={() => run(() => api.checkBuiltinModel(m.id))}>{busy ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t('Check files')}</button>
      <button type="button" className="ghost" disabled={busy} onClick={() => setConfirm('remove')}>{t('Remove')}</button></div>}
    {state === 'remove_failed' && <div className="actions"><button type="button" className="ghost" disabled={busy} onClick={() => setConfirm('remove')}>{t('Remove')}</button></div>}
    <ConfirmDialog open={confirm === 'install'} dark={dark} neutral title={t('Download {model}?', { model: m.name })}
      description={(runtimeExtra
        ? t('The model file ({size}) is downloaded once from Hugging Face, with llama.cpp ({runtime}) from GitHub to run it, into the DEIXIS data folder.', { size: formatBytes(m.bytes), runtime: formatBytes(runtimeExtra) })
        : t('The model file ({size}) is downloaded once from Hugging Face into the DEIXIS data folder.', { size: formatBytes(m.bytes) }))
        + ' ' + t('After that, it runs on this computer and sends no text off it.')}
      context={builtin.path} confirmLabel={t('Download')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(() => api.installBuiltinModel(m.id))} onOpenChange={open => setConfirm(open ? 'install' : null)} />
    <ConfirmDialog open={confirm === 'remove'} dark={dark} title={t('Remove {model}?', { model: m.name })}
      description={t('Its file is deleted. Scores it already gave are kept; sources not yet scored are ranked without it until you download it again.')}
      confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={() => run(() => api.removeBuiltinModel(m.id))} onOpenChange={open => setConfirm(open ? 'remove' : null)} />
  </section>
}

// The earlier PyTorch built-in model (D88): its measured size, removed only when the person asks.
function BuiltinLegacy({ builtin, dark, onChanged }: { builtin: BuiltinModels; dark: boolean; onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  if (!builtin.legacy.present) return null
  const remove = () => {
    setBusy(true)
    api.removeBuiltinLegacy().then(() => { setOpen(false); toast('success', t('The earlier built-in model was removed.')); return onChanged() })
      .catch((e: Error) => toast('error', e.message)).finally(() => setBusy(false))
  }
  return <div className="builtin-legacy">
    <span><HardDrive size={14} aria-hidden />{t('Earlier built-in model (PyTorch) · {size}', { size: formatBytes(builtin.legacy.bytes) })}</span>
    <button type="button" className="ghost" disabled={busy} onClick={() => setOpen(true)}><Trash2 size={14} aria-hidden />{t('Remove')}</button>
    <ConfirmDialog open={open} dark={dark} title={t('Remove the earlier built-in model?')}
      description={t('The PyTorch model files and the Python environment the earlier version of DEIXIS used are deleted ({size}). The current built-in models do not use them. Scores it already gave are kept.', { size: formatBytes(builtin.legacy.bytes) })}
      context={builtin.path} confirmLabel={t('Remove')} cancelLabel={t('Cancel')} busy={busy} onConfirm={remove} onOpenChange={setOpen} />
  </div>
}

// Turns the bare site addresses in a settings sentence (openalex.org, zotero.org/settings/keys) into links.
function linkify(text: string): ReactNode {
  return text.split(/(\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:org|com|uk|gov|ai|dev)(?:\/[\w/#?=.-]*[\w/])?)/).map((part, i) => i % 2
    ? <a key={i} href={`https://${part}`} target="_blank" rel="noopener noreferrer">{part}</a> : part)
}

// A check button. The check to run reaches it as a prop, so no render-time helper is handed a function that touches a ref.
function CheckButton({ id, label, run, checking, start, disabled = false, quiet = false }: {
  id: string; label: string; run: () => Promise<unknown>; checking: string | null
  start: (key: string, check: () => Promise<unknown>) => void; disabled?: boolean; quiet?: boolean
}) {
  return <button type="button" className={quiet ? 'ghost' : 'btn-pri'} disabled={disabled || checking !== null} onClick={() => start(id, run)}>{checking === id ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t(label)}</button>
}

// Reranking (a built-in catalog reranker or an API one): off until turned on; reorders the first records of the fused order (the papers a
// run reads times the pool factor) before they are read, so it decides which records fall above the read cutoff. It never includes or excludes, and the person's own included records stay first.
function RerankingSettings({ refresh, dark, keyField, builtin, onBuiltinChanged }: { refresh: string; dark: boolean; keyField: (env: string, service: string) => ReactNode; builtin: BuiltinModels | null; onBuiltinChanged: () => Promise<void> }) {
  const [state, setState] = useState<Reranking | null>(null)
  const [timeout, setTimeout_] = useState<string | null>(null)
  const [modelSheet, setModelSheet] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sheet, setSheet] = useState<'off' | RerankProvider | null>(null)
  const toast = useToast()
  useEffect(() => {
    api.reranking().then(result => { setState(result); setError('') }).catch((e: Error) => { if (!isLeft(e)) setError(e.message) })
  }, [refresh])
  if (!state) return error ? <Notice tone="error" panel="search">{error}</Notice> : null
  const shown = { enabled: state.enabled, provider: state.provider, model: state.model, factor: state.pool_factor, timeout: state.timeout_seconds }
  const option = (p: RerankProvider) => state.options.find(o => o.provider === p)
  const builtinOption = (id: string) => state.options.find(o => o.provider === 'builtin' && o.model === id)
  // A built-in reranker is in use only when the saved provider and model are both it.
  const builtinInUse = shown.enabled && shown.provider === 'builtin' ? shown.model : null
  const save = (next: typeof shown) => {
    setBusy(true); setError('')
    api.saveReranking({ enabled: next.enabled, provider: next.provider, model: next.provider === 'builtin' ? next.model : null, pool_factor: next.factor, timeout_seconds: next.timeout })
      .then(result => { setState(result); setTimeout_(null); toast('success', t('Reranking setting saved.')) })
      .catch((e: Error) => setError(t('Could not save: {message}', { message: e.message })))
      .finally(() => setBusy(false))
  }
  // The limits of the reranker in use, folded under Advanced in its sheet; each change is saved at once.
  const saveTimeout = () => {
    const value = Number(timeout)
    if (timeout === null || !Number.isInteger(value) || value < 10 || value > 900 || value === shown.timeout) { setTimeout_(null); return }
    save({ ...shown, timeout: value })
  }
  const limits = <details className="way-more rerank-limits">
    <summary><ChevronRight size={14} aria-hidden />{t('Advanced')}</summary>
    <div className="rerank-limit">
      <span id="rerank-factor-label">{t('Records reranked')}</span>
      <span className="seg" role="group" aria-labelledby="rerank-factor-label">
        {[1, 2, 4].map(f => <button key={f} type="button" className={shown.factor === f ? 'on' : ''} aria-pressed={shown.factor === f} disabled={busy}
          onClick={() => { if (shown.factor !== f) save({ ...shown, factor: f }) }}>{f === 4 ? t('{n}× (recommended)', { n: f }) : `${f}×`}</button>)}
      </span>
    </div>
    <p className="foot-note">{t('× the papers a run reads. On Standard, 200 records are reranked for 50 read.')}</p>
    <div className="rerank-limit">
      <label htmlFor="rerank-timeout">{t('Time limit')}</label>
      <span className="rerank-timeout">
        <input id="rerank-timeout" className="field" type="number" min={10} max={900} step={1} inputMode="numeric" value={timeout ?? String(shown.timeout)} disabled={busy}
          onChange={e => setTimeout_(e.target.value)} onBlur={saveTimeout} onKeyDown={e => { if (e.key === 'Enter') saveTimeout() }} />
        <span>{t('s')}</span>
        <span className="info-tip" tabIndex={0} role="img" aria-label={t('When the reranker fails or runs out of time, the run keeps the fused order and says so; no other reranker is used.')}
          title={t('When the reranker fails or runs out of time, the run keeps the fused order and says so; no other reranker is used.')}><Info size={14} aria-hidden /></span>
      </span>
    </div>
  </details>
  // One card per reranker, grouped like the model cards (on this computer, then APIs); a card opens its sheet, where it
  // is chosen. Choosing saves at once, with the limits as they stand.
  // API rerankers: where the key comes from and what each sends; the model name comes from the server's options.
  const apis = [
    ['voyage', t('Voyage AI reranker'), 'rerank-3-lite', 'VOYAGE_API_KEY', 'Voyage AI', 'dashboard.voyageai.com'],
    ['cohere', t('Cohere reranker'), 'rerank-v4.0-fast', 'COHERE_API_KEY', 'Cohere', 'dashboard.cohere.com/api-keys'],
    ['jina', t('Jina AI reranker'), 'jina-reranker-v3.5', 'JINA_API_KEY', 'Jina AI', 'jina.ai/api-dashboard'],
    ['zeroentropy', t('ZeroEntropy reranker'), 'zerank-2', 'ZEROENTROPY_API_KEY', 'ZeroEntropy', 'dashboard.zeroentropy.dev'],
  ] as const
  const rows: { id: 'off' | RerankProvider; local: boolean | null; label: string; model: string; desc: ReactNode; key?: { env: string; service: string; site: string } }[] = [
    ...apis.map(([id, label, fallback, env, service, site]) => ({ id, local: false, label, model: option(id)?.model ?? fallback,
      desc: withCode(t('{model} · sends the question and titles and abstracts to {service}', { service }), { model: option(id)?.model ?? fallback }),
      key: { env, service, site } })),
    { id: 'off', local: null, label: t('Off'), model: t('The fused ranking is read as it is.'), desc: t('The fused ranking is read as it is.') },
  ]
  const stateOf = (id: 'off' | RerankProvider) => {
    const o = id === 'off' ? null : option(id)
    const checked = id === 'off' ? !shown.enabled : shown.enabled && shown.provider === id
    const available = id === 'off' || !!o?.available
    // A card's pill stays short ("Key needed"); the sheet's key section says which key and where to get it.
    const need = available ? null : t('Key needed')
    return { o, checked, available, status: need ?? (checked ? t('In use') : t('Not in use')) }
  }
  const card = (row: (typeof rows)[number]) => {
    const { checked, available, status } = stateOf(row.id)
    return <CompanyCard key={row.id} mark={companyMark(undefined, undefined, settingsIcon(row.id))} name={row.label}
      maker={row.id === 'off' ? row.model : <code className="model-id">{row.model}</code>} ready={checked && available} status={status} active={checked} compact onClick={() => setSheet(row.id)} />
  }
  const open = rows.find(r => r.id === sheet)
  const openState = open ? stateOf(open.id) : null
  const openModel = builtin?.models.find(m => m.id === modelSheet && m.kind === 'reranker') ?? null
  const openModelOption = openModel ? builtinOption(openModel.id) : undefined
  const openModelInUse = !!openModel && builtinInUse === openModel.id
  return <>
    <h2 id="reranking-title" data-panel="search">{t('Reranking')}</h2>
    <p className="foot-note" data-panel="search">{t('Reorders the top of the ranking by reading the question with each title and abstract, before records are read, so it decides which papers fall within the reading limit. Only the record order is reranked; passages for answers are not. A reranker score never includes or excludes a record, and records you included stay first.')}</p>
    {error && <Notice tone="error" panel="search">{error}</Notice>}
    {state.builtin_model_changed && <Notice tone="attention" panel="search">{t('The built-in reranker chosen earlier is not available in this version of DEIXIS. Pick a reranker below; DEIXIS does not switch to another one by itself.')}</Notice>}
    <div className="choice-groups" data-panel="search" data-group="reranking" aria-busy={busy || undefined}>
      <h3 className="choice-head">{t('Local models')}</h3>
      {builtin && <BuiltinCatalog builtin={builtin} kind="reranker" inUse={builtinInUse} onOpen={setModelSheet} />}
      <h3 className="choice-head">{t('API models')}</h3>
      <div className="co-grid">{rows.filter(r => r.local === false).map(card)}</div>
      <div className="co-grid choice-off">{rows.filter(r => r.local === null).map(card)}</div>
    </div>
    {builtin && <BuiltinModelSheet builtin={builtin} model={openModel} dark={dark} onClose={() => setModelSheet(null)} onChanged={onBuiltinChanged}
      use={openModel && <section className={`way ${openModelInUse ? 'is-on' : ''}`} aria-label={t('Reranking')}>
        <div className="way-head"><h3>{t('Reranking')}</h3><span className={`st ${openModelInUse && openModelOption?.available ? 'ok' : 'no'}`}>{openModelInUse ? t('In use') : openModelOption?.available ? t('Not in use') : t(openModelOption?.reason ?? 'Not downloaded')}</span></div>
        <p className="way-desc">{t('No text leaves the computer.')}</p>
        {!openModelInUse && <div className="actions">
          <button type="button" className="btn-pri" disabled={!openModelOption?.available || busy} aria-describedby={!openModelOption?.available ? 'builtin-rerank-why' : undefined}
            onClick={() => { save({ ...shown, enabled: true, provider: 'builtin', model: openModel.id }); setModelSheet(null) }}>
            {busy ? <span className="spin" aria-hidden /> : <CircleCheck aria-hidden />}{t('Use this reranker')}</button>
          {!openModelOption?.available && <span className="sr-only" id="builtin-rerank-why">{t('Download the model first.')}</span>}
        </div>}
        {openModelInUse && limits}
      </section>} />}
    <Sheet open={!!open} onOpenChange={next => { if (!next) setSheet(null) }}>
      <SheetContent className={`detail-sheet connection-sheet ${dark ? 'dark' : ''}`}>
        {open && openState && <>
          <SheetHeader className="sheet-head">
            <span className="sheet-mark" aria-hidden>{settingsIcon(open.id)}</span>
            <div className="sheet-head-text">
              <SheetTitle>{open.label}</SheetTitle>
              <SheetDescription>{t('Reranking')}</SheetDescription>
            </div>
          </SheetHeader>
          <div className="connection-body mk pad detail">
            <p className="foot-note is-ink">{open.desc}</p>
            {open.key && <section className={`way ${openState.available ? 'is-on' : ''}`} aria-label={t('With an API key')}>
              <div className="way-head"><h3>{t('With an API key')}</h3><span className={`st ${openState.available ? 'ok' : 'no'}`}>{openState.available ? t('Ready') : t('No key entered')}</span></div>
              <p className="way-desc">{linkify(t('Get the key at {site}.', { site: open.key.site }))}</p>
              {keyField(open.key.env, open.key.service)}
            </section>}
            <section className={`way ${openState.checked ? 'is-on' : ''}`} aria-label={t('Reranking')}>
              <div className="way-head"><h3>{t('Reranking')}</h3><span className={`st ${openState.checked && openState.available ? 'ok' : 'no'}`}>{openState.status}</span></div>
              {open.id !== 'off' && openState.o?.sends && <p className="way-desc">{t(openState.o.sends)}</p>}
              {!openState.checked && <div className="actions">
                <button type="button" className="btn-pri" disabled={!openState.available || busy}
                  onClick={() => { save({ ...shown, enabled: open.id !== 'off', provider: open.id === 'off' ? shown.provider : open.id }); setSheet(null) }}>
                  {busy ? <span className="spin" aria-hidden /> : <CircleCheck aria-hidden />}{open.id === 'off' ? t('Turn reranking off') : t('Use this reranker')}</button>
              </div>}
              {openState.checked && open.id !== 'off' && limits}
            </section>
          </div>
        </>}
      </SheetContent>
    </Sheet>
  </>
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
  const [over, setOver] = useState(false)
  return <div className="reference-import">
    <input ref={input} type="file" accept=".bib,.ris,.bibtex,text/plain" hidden onChange={e => choose(e.target.files?.[0])} />
    <div className={`ref-drop${over ? ' is-over' : ''}${busy ? ' is-busy' : ''}`}
      onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); choose(e.dataTransfer.files?.[0]) }}>
      <span className="ref-drop-ico" aria-hidden>{busy ? <span className="spin" /> : <FileUp />}</span>
      <p className="ref-drop-title">{t(busy ? 'Importing…' : 'Drop a .bib or .ris file here')}</p>
      <p className="ref-drop-sub">{t('Exported from Zotero, Mendeley, EndNote or JabRef')}</p>
      <button type="button" className="btn-pri" disabled={busy} onClick={() => input.current?.click()}><Upload aria-hidden />{t('Choose a .bib or .ris file')}</button>
    </div>
    {error && <p className="key-form-error" role="alert">{error}</p>}
    {result && <div className="reference-result" role="status">
      <p>{t('{file}: {n} entries read. {saved} saved to the Library, {already} were already there.', { file: result.filename ?? t('The file'), n: entries.length, saved: result.saved.length, already: result.already_saved.length })}</p>
      <dl className="ref-stats">
        <div><dt>{t('Saved')}</dt><dd>{result.saved.length}</dd></div>
        <div><dt>{t('Already there')}</dt><dd>{result.already_saved.length}</dd></div>
        <div><dt>{t('Matched by DOI')}</dt><dd>{confirmed}</dd></div>
        <div><dt>{t('Kept as written')}</dt><dd>{own}</dd></div>
      </dl>
      {result.errors.length > 0 && <>
        <p>{t('{n} entries could not be read and were left out:', { n: result.errors.length })}</p>
        <ul>{result.errors.slice(0, 20).map((err, i) => <li key={i}>{t('Line {line}', { line: err.line })}{err.key ? ` · ${err.key}` : ''}: {err.message}</li>)}</ul>
      </>}
    </div>}
    <section className="sheet-card ref-how" aria-label={t('How entries are kept')}>
      <h3 className="sheet-card-title">{t('How entries are kept')}</h3>
      <ul>
        <li><BadgeCheck aria-hidden /><p><b>{t('DOI confirmed')}</b>{t('When OpenAlex or Crossref confirms an entry’s DOI, that provider’s record is used.')}</p></li>
        <li><PenLine aria-hidden /><p><b>{t('Kept as written')}</b>{t('Other entries are kept as you wrote them and marked as not confirmed.')}</p></li>
      </ul>
    </section>
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
  const [mathpix, setMathpix] = useState<Mathpix | null>(null)
  const [ocrTool, setOcrTool] = useState<OcrTool | null>(null)
  const [pdfReader, setPdfReader] = useState<PdfReader | null>(null)
  const [semantic, setSemantic] = useState<SemanticSearch | null>(null)
  const [semError, setSemError] = useState('')
  const [pending, setPending] = useState<{ provider: SemanticSearchProvider; model: string | null } | null>(null)
  const [builtin, setBuiltin] = useState<BuiltinModels | null>(null)
  const [builtinSheet, setBuiltinSheet] = useState<string | null>(null)  // the built-in embedding model whose sheet is open
  // What this sheet checked itself, and when the answer came: "checked HH:MM" belongs to that answer only.
  const [checking, setChecking] = useState<string | null>(null)
  const [showing, setShowing] = useState<string | null>(null)  // the hidden model being offered again
  const [checked, setChecked] = useState<Record<string, number>>({})
  const [checkFailed, setCheckFailed] = useState<Record<string, string>>({})
  // The sign-in DEIXIS started for a tool (D21); it is polled while the person finishes it in the terminal window that opened.
  const [signInRuns, setSignInRuns] = useState<Record<string, AccountSignIn>>({})
  const signInSeen = useRef(false)
  // One counter per tool, moved on by every start and cancel: an answer to an earlier request that arrives after a
  // later one began (a poll that was in flight when the person cancelled) is dropped, never shown.
  const signInVersion = useRef<Record<string, number>>({})
  const signInVersionOf = (tool: string) => signInVersion.current[tool] ?? 0  // a tool never started on this page (re-attached) is at 0
  const nextSignIn = (tool: string) => (signInVersion.current[tool] = signInVersionOf(tool) + 1)
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
  // The all-connections read and each single-connection check order their answers per connection through one counter (E7).
  const order = useRef(createRequestOrder())
  // Reads are cancelled when the page is left and end with "did not answer" when they take too long; saves and other writes are not (E25).
  const leaving = useLeaving()

  const load = useCallback((refresh: boolean) => {
    const n = ++seq.current.connections
    const ticket = order.current.start()
    return api.connections(refresh, leaving()).then(result => {
      if (n !== seq.current.connections) return
      // A connection checked on its own after this read began keeps that newer answer.
      const taken = new Set(Object.keys(result.models).filter(id => order.current.settle(id, ticket)))
      setData(old => ({ ...result, models: Object.fromEntries(Object.entries(result.models).map(([id, health]) => [id, taken.has(id) ? health : old?.models[id] ?? health])) }))
      setError('')
      // A sign-in still running on the backend when this page opened again: picked up from the first read only, and
      // polling carries on from there. Later reads never bring back one that was cancelled or finished.
      if (!signInSeen.current) {
        signInSeen.current = true
        const running = Object.entries(result.sign_ins ?? {}).filter(([, run]) => run.state === 'waiting')
        if (running.length) setSignInRuns(current => ({ ...Object.fromEntries(running), ...current }))
      }
    })
      .catch((e: Error) => {
        if (gaveNoAnswer(e)) order.current.release(ticket)
        if (n === seq.current.connections && !isLeft(e)) setError(t('Connections could not be read: {message}', { message: e.message }))
      })
  }, [leaving])
  const loadCredentials = useCallback(() => { api.credentials(leaving()).then(setCredentials).catch((e: Error) => { if (!isLeft(e)) setError(t('Stored keys could not be read: {message}', { message: e.message })) }) }, [leaving])
  // A read that a check asked for (`strict`) rejects when it fails, so the check is reported as not run, never as a fresh
  // result over the old state. It resolves false when a later read replaced it (the check then shows no time either).
  const loadTools = useCallback((refresh: boolean, strict = false): Promise<boolean> => {
    const n = ++seq.current.tools
    return api.localTools(refresh, leaving()).then(result => { if (n !== seq.current.tools) return false; setTools(result); setToolsError(''); return true })
      .catch((e: Error) => { if (n === seq.current.tools && !isLeft(e)) setToolsError(e.message); if (strict) throw e; return false })
  }, [leaving])
  const loadReader = useCallback((strict = false): Promise<boolean> => api.equationReader(leaving()).then(result => { setReader(result); return true })
    .catch((e: Error) => { if (!isLeft(e)) setToolsError(e.message); if (strict) throw e; return false }), [leaving])
  const loadMathpix = useCallback((strict = false): Promise<boolean> => api.mathpix(leaving()).then(result => { setMathpix(result); return true })
    .catch((e: Error) => { if (!isLeft(e)) setToolsError(e.message); if (strict) throw e; return false }), [leaving])
  const loadOcr = useCallback((strict = false): Promise<boolean> => api.ocr(leaving()).then(result => { setOcrTool(result); return true })
    .catch((e: Error) => { if (!isLeft(e)) setToolsError(e.message); if (strict) throw e; return false }), [leaving])
  const loadSemantic = useCallback((strict = false): Promise<boolean> => {
    const n = ++seq.current.semantic, version = seq.current.semanticVersion, duringSave = seq.current.saving
    const current = () => n === seq.current.semantic && version === seq.current.semanticVersion && !duringSave
    return api.semanticSearch(leaving()).then(result => { if (!current()) return false; setSemantic(result); setSemError(''); return true })
      .catch((e: Error) => { if (current() && !isLeft(e)) setSemError(e.message); if (strict) throw e; return false })
  }, [leaving])
  const loadBuiltin = useCallback(() => api.builtinModels(leaving()).then(setBuiltin).catch((e: Error) => { if (!isLeft(e)) setSemError(e.message) }), [leaving])
  useEffect(() => { void load(false) }, [load])
  useEffect(() => { loadCredentials() }, [loadCredentials])
  useEffect(() => { void loadTools(false) }, [loadTools])
  useEffect(() => { void loadSemantic() }, [loadSemantic])
  useEffect(() => { void loadBuiltin() }, [loadBuiltin])
  useEffect(() => {
    if (!builtin?.models.some(m => m.state === 'installing' || m.state === 'installing_elsewhere' || m.state === 'removing')) return
    const timer = window.setInterval(() => { void loadBuiltin().then(() => loadSemantic()) }, 1500)
    return () => window.clearInterval(timer)
  }, [builtin, loadBuiltin, loadSemantic])
  useEffect(() => { void loadReader() }, [loadReader])
  useEffect(() => { void loadOcr() }, [loadOcr])
  useEffect(() => { void loadMathpix() }, [loadMathpix])
  useEffect(() => {
    if (!mathpix?.reading) return
    const timer = window.setInterval(() => { void loadMathpix() }, 10000)
    return () => window.clearInterval(timer)
  }, [mathpix, loadMathpix])
  useEffect(() => {
    if (ocrTool?.job?.status !== 'running') return
    const timer = window.setInterval(() => { void loadOcr() }, 1500)
    return () => window.clearInterval(timer)
  }, [ocrTool, loadOcr])
  useEffect(() => { api.pdfReader(leaving()).then(setPdfReader, (e: Error) => { if (!isLeft(e)) setToolsError(e.message) }) }, [leaving])
  useEffect(() => {
    if (reader?.job?.status !== 'running' && !reader?.reading) return
    const timer = window.setInterval(() => { void loadReader() }, reader?.job?.status === 'running' ? 2000 : 10000)
    return () => window.clearInterval(timer)
  }, [reader, loadReader])
  useEffect(() => {
    if (!tools?.tools.some(tool => tool.job?.status === 'running' || tool.pull?.status === 'running')) return
    const timer = window.setInterval(() => { void loadTools(false) }, tools.tools.some(tool => tool.pull?.status === 'running') ? 1000 : 2000)
    return () => window.clearInterval(timer)
  }, [tools, loadTools])

  const reloadTools = useCallback(() => loadTools(true).then(() => undefined), [loadTools])
  const reloadReader = useCallback(() => loadReader().then(() => undefined), [loadReader])
  // A check of one connection: its answer is shown only if no later request for that connection started before it came back.
  const readModel = useCallback((id: string) => {
    const n = order.current.start(id)
    return api.modelConnection(id, true, leaving()).then(result => {
      if (order.current.settle(id, n)) setData(current => current ? { ...current, models: { ...current.models, [id]: result } } : current)
    }, (e: Error) => { if (gaveNoAnswer(e)) order.current.release(n); throw e })
  }, [leaving])
  const reloadAfterKeyChange = useCallback(() => { loadCredentials(); void load(true); void loadSemantic() }, [loadCredentials, load, loadSemantic])
  // A model key change also re-checks that one connection on its own: the full refresh waits on every connection
  // (about 12 s with the CLIs), and until then the card would still show the state before the change.
  const reloadAfterModelKeyChange = useCallback((conn: string) => {
    reloadAfterKeyChange()
    void readModel(conn).catch(() => {})
  }, [reloadAfterKeyChange, readModel])
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
  const refreshModel = (id: string) => readModel(id).catch((e: Error) => { toast('error', t('Check failed: {message}', { message: e.message })); throw e })
  const settleSignIn = useCallback((tool: string, run: AccountSignIn, version: number) => {
    if ((signInVersion.current[tool] ?? 0) !== version) return
    setSignInRuns(current => ({ ...current, [tool]: run }))
    if (run.state !== 'succeeded' && run.state !== 'session_confirmed') return
    if (run.state === 'succeeded') toast('success', t('Signed in to {name}.', { name: ACCOUNT_TOOLS[tool]?.name ?? tool }))
    void readModel(tool).catch(() => undefined)
    void loadTools(true)
  }, [toast, loadTools, readModel])
  const startSignIn = (tool: string) => {
    const version = nextSignIn(tool)
    api.startAccountSignIn(tool).then(run => settleSignIn(tool, run, version), (e: Error) => {
      if (signInVersionOf(tool) !== version) return
      setSignInRuns(current => ({ ...current, [tool]: { state: 'failed', message: e.message } }))
      toast('error', t('Could not start the sign-in: {message}', { message: e.message }))
    })
  }
  const cancelSignIn = (tool: string) => {
    const version = nextSignIn(tool)
    api.cancelAccountSignIn(tool).then(run => {
      if (signInVersionOf(tool) !== version) return
      setSignInRuns(({ [tool]: _gone, ...rest }) => run.state === 'idle' ? rest : { ...rest, [tool]: run })
    }, (e: Error) => toast('error', t('Could not cancel the sign-in: {message}', { message: e.message })))
  }
  const waitingSignIns = Object.keys(signInRuns).filter(tool => signInRuns[tool].state === 'waiting').sort().join(',')
  useEffect(() => {
    if (!waitingSignIns) return
    const tools = waitingSignIns.split(',')
    const timer = window.setInterval(() => {
      for (const tool of tools) {
        const version = signInVersionOf(tool)
        api.accountSignIn(tool).then(run => settleSignIn(tool, run, version), () => undefined)
      }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [waitingSignIns, settleSignIn])
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
    : m.verification === 'pending' ? ['warn', t('Saved · not verified')]
    : m.verification === 'rejected' ? ['warn', t('Key refused')]
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
  const mathpixStatus = (): [Tone, string] => !mathpix ? (toolsError ? unknown : loading)
    : mathpix.keys_rejected ? ['warn', t('Key pair refused')] : !mathpix.pair.configured ? ['no', t('Not set up')]
    : mathpix.switch === 'on' ? ['ok', t('On')] : ['no', t('Off')]
  const providerStatus = (mode: string | null, keyBroken = false): [Tone, string] => keyBroken ? ['warn', t('Key broken')] : mode === 'api_key' ? ['ok', t('Key configured')] : mode === 'keyless' ? ['ok', t('No key needed')] : ['no', t('Not set up')]
  const zoteroStatus = (): [Tone, string] => !zotero ? (tools ? ['no', t('Not set up')] : toolsError ? unknown : loading)
    : zotero.running && zotero.local_api ? ['ok', t('Local API on')] : zotero.web_configured ? ['ok', t('zotero.org set')]
    : zotero.installed ? ['no', t(zotero.running ? 'Local API off' : 'Not running')] : ['no', t('Not set up')]
  const tile = (key: string, kind: Selected['kind'], id: string, name: string, desc: string, [tone, status]: [Tone, string]) =>
    <Tile key={key} icon={settingsIcon(key)} name={name} desc={desc} tone={tone} status={status} active={isActive(kind, id)} onClick={() => show({ kind, id })} />

  // A company card is ready when one of its connections says it is; the line under it says which, from the same state.
  const companyState = (c: Company): { ready: boolean; status: string; via: string } => {
    if (!data) return { ready: false, status: error ? t('Not known') : t('Checking…'), via: '' }
    const acc = c.account ? data.models[c.account.conn] : undefined
    const key = c.key ? data.models[c.key.conn] : undefined
    const a = !!acc?.ready, k = !!key?.ready
    const via = a && k ? t('Connected with your account and an API key') : a ? t('Connected with your account') : k ? t('Connected with an API key')
      : key?.verification === 'pending' ? t('API key saved · not verified') : key?.key_configured ? t('API key saved · not ready') : acc?.signed_in ? t('Signed in · not ready')
      : t(c.account && c.key ? 'Connect with your account or an API key' : c.account ? 'Connect with your account' : 'Connect with an API key')
    return { ready: a || k, status: t(a || k ? 'Ready' : key?.verification === 'pending' ? 'Saved · not verified' : 'Not connected'), via }
  }
  const companyCard = (c: Company, compact = false) => {
    const state = companyState(c)
    return <CompanyCard key={c.id} mark={companyMark(c.icon, c.mono)} name={c.name} maker={t(c.maker)} via={compact ? undefined : state.via} ready={state.ready}
      status={state.status} active={isActive('company', c.id)} compact={compact} onClick={() => show({ kind: 'company', id: c.id })} />
  }
  // Older connections stay listed while their key is saved, so nobody loses one they set up.
  const others = OTHER_COMPANIES.filter(c => !c.onlyWhenSet || (!!c.key && (!!data?.models[c.key.conn]?.key_configured || !!keyEntry(c.key.env)?.configured)))
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
    { kind: 'ocr-tool', id: 'tesseract', name: 'Scanned PDF reader (OCR)', what: 'Turns scanned pages into text with Tesseract', status: ocrStatus() },
    { kind: 'equation-reader', id: 'marker', name: 'Equation reader', what: 'Reads equations as LaTeX', status: readerStatus() },
  ]
  const saveLocalServer = (url: string) => {
    setServerBusy(true); setServerError('')
    const n = order.current.start('local_server')
    api.saveLocalServer(url).then(result => {
      if (order.current.settle('local_server', n)) setData(current => current ? { ...current, models: { ...current.models, local_server: { ...result, connection: 'local_server' } } } : current)
      setServerDraft(null)
      toast('success', url ? t('Local server address saved.') : t('Local server address removed.'))
    }).catch((e: Error) => setServerError(e.message)).finally(() => setServerBusy(false))
  }
  // Semantic search rows (plan ST5); "Local model server" (Ollama, LM Studio) only while it is the saved choice. A row that
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
    if (row === 'voyage') return option('voyage')?.available ? null : t('Needs a Voyage AI key')
    if (row === 'cohere') return option('cohere')?.available ? null : t('Needs a Cohere key')
    if (row === 'server') return serverChoices.length ? null : serverOptions.some(o => /lists no embedding model/.test(o.reason ?? '')) ? t('Needs an embedding model') : t('Needs a local server')
    return null
  }
  const semanticRows: { id: string; label: string; local: boolean | null; model?: string; apiKey?: { env: string; site: string; service: string; conn?: string }; desc?: ReactNode; providers: SemanticSearchProvider[]; body?: ReactNode }[] = [
    { id: 'gemini', providers: ['gemini'], label: t('Gemini embeddings'), local: false, model: option('gemini')?.models[0] ?? 'gemini-embedding',
      desc: withCode(t('{model} · sends titles, abstracts and passage text to Google'), { model: option('gemini')?.models[0] ?? 'gemini-embedding' }),
      apiKey: { env: 'GEMINI_API_KEY', site: 'aistudio.google.com/apikey', service: 'Google AI Studio', conn: 'gemini' },
      body: <p className="foot-note is-ink">{t('Reads the question in any language. Needs a Google AI Studio key; a free key works.')}</p> },
    { id: 'openai', providers: ['openai'], label: t('OpenAI embeddings'), local: false, model: option('openai')?.models[0] ?? 'text-embedding-3-small',
      desc: withCode(t('{model} · sends titles, abstracts and passage text to OpenAI'), { model: option('openai')?.models[0] ?? 'text-embedding-3-small' }),
      apiKey: { env: 'OPENAI_API_KEY', site: 'platform.openai.com', service: 'OpenAI', conn: 'openai' } },
    { id: 'voyage', providers: ['voyage'], label: t('Voyage AI embeddings'), local: false, model: option('voyage')?.models[0] ?? 'voyage-4-lite',
      desc: withCode(t('{model} · sends titles, abstracts and passage text to Voyage AI'), { model: option('voyage')?.models[0] ?? 'voyage-4-lite' }),
      apiKey: { env: 'VOYAGE_API_KEY', site: 'dashboard.voyageai.com', service: 'Voyage AI' } },
    { id: 'cohere', providers: ['cohere'], label: t('Cohere embeddings'), local: false, model: option('cohere')?.models[0] ?? 'embed-v5.0-fast',
      desc: withCode(t('{model} · sends titles, abstracts and passage text to Cohere'), { model: option('cohere')?.models[0] ?? 'embed-v5.0-fast' }),
      apiKey: { env: 'COHERE_API_KEY', site: 'dashboard.cohere.com/api-keys', service: 'Cohere' } },
    // Local model servers are no longer offered (the built-in models cover keyless use); a saved Ollama or LM Studio
    // choice still shows its row, so it is never switched away without the person choosing another.
    ...(semantic && SERVER_IDS.includes(semantic.provider)
      ? [{ id: 'server', providers: ['ollama', 'lm_studio'] as SemanticSearchProvider[], label: t('Local model server'), local: true, model: 'Ollama · LM Studio', desc: t('An embedding model on Ollama or LM Studio') }] : []),
    { id: 'off', providers: ['off'], label: t('Off'), local: null, model: t('Keyword search only; sources get no similarity score.'), desc: t('Keyword search only; sources get no similarity score.') },
  ]
  const privacyOf = (provider: SemanticSearchProvider) => provider === 'off' ? t('Sources get no similarity score; passages are ranked by keyword match only. No text is sent anywhere.')
    : provider === 'gemini' ? t('Passage text is sent to Google. If your key is on Google’s free tier, which DEIXIS cannot detect, Google may use that text to improve its products.')
    : provider === 'openai' ? t('Passage text is sent to {service}.', { service: 'OpenAI' })
    : provider === 'cohere' ? t('The question, titles, abstracts and passage text are sent to {service}. Each run records the tokens Cohere billed.', { service: 'Cohere' })
    : provider === 'voyage' ? t('The question, titles, abstracts and passage text are sent to {service}. Each run records the tokens Voyage counted.', { service: 'Voyage AI' })
    : provider === 'builtin' ? t('For semantic search, no text leaves the computer.') : t('Passage text stays on this computer.')
  const privacy = semantic ? privacyOf(semantic.provider) : null
  // A semantic search row's state: chosen, choosable, and what its card's pill says.
  const semanticState = (row: (typeof semanticRows)[number]) => {
    const isChosen = !!chosen && row.providers.includes(chosen.provider)
    const available = !!semantic && (row.id === 'server' ? serverChoices.length > 0 : !!option(row.providers[0])?.available)
    const need = needsPill(row.id)
    return { isChosen, available, need, status: need ?? (isChosen ? t('In use') : t('Not in use')) }
  }
  const pickSemantic = (row: (typeof semanticRows)[number]) => {
    if (row.id === 'server') { const first = serverChoices[0]; if (first) chooseSemantic(first.provider, first.model) }
    else chooseSemantic(row.providers[0], null)
  }
  const semanticRow = selected?.kind === 'semantic' ? semanticRows.find(r => r.id === selected.id) : undefined
  // The built-in embedding models: one choice per catalog model, in use only when the provider and the model are both it.
  const builtinOption = (id: string) => semantic?.options.find(o => o.provider === 'builtin' && o.model === id)
  const builtinChosen = chosen?.provider === 'builtin' ? chosen.model : null
  const builtinModel = builtin?.models.find(m => m.id === builtinSheet && m.kind === 'embedding') ?? null
  const builtinModelOption = builtinModel ? builtinOption(builtinModel.id) : undefined
  const builtinModelChosen = !!builtinModel && builtinChosen === builtinModel.id
  const builtinReady = !!builtinModel && !!builtinModelOption?.available
  const builtinChanged = async () => { await loadBuiltin(); await loadSemantic() }

  // ---- the connection sheet ----
  const sel = selected
  const company = sel?.kind === 'company' ? COMPANIES.find(c => c.id === sel.id) : undefined
  const provider = sel?.kind === 'provider' ? data?.providers.find(p => p.id === sel.id) : undefined
  // The sheet title carries the same mark as the card or tile it opened from.
  const sheetIcon = !sel ? null
    : company ? (company.icon ? <ConnectionIcon id={company.icon} /> : company.mono ? <span className="sheet-mono" aria-hidden>{company.mono}</span> : null)
    : sel.kind === 'local' ? settingsIcon(sel.id === 'local_server' ? 'server' : sel.id)
    : settingsIcon(sel.kind === 'ocr-tool' ? 'ocr' : sel.kind === 'pdf-reader' ? 'pymupdf' : sel.kind === 'reference-files' ? 'reference-files' : sel.id)
  const name = !sel ? ''
    : company ? company.name
    : sel.kind === 'local' ? (sel.id === 'local_server' ? t('Another local server') : localToolNames[sel.id] ?? sel.id)
    : sel.kind === 'semantic' ? semanticRow?.label ?? sel.id
    : sel.kind === 'provider' ? providerNames[sel.id] ?? sel.id
    : sel.kind === 'equation-reader' ? t('Equation reader (Marker)')
    : sel.kind === 'mathpix' ? t('Mathpix equation reader')
    : sel.kind === 'ocr-tool' ? t('OCR (Tesseract)')
    : sel.kind === 'pdf-reader' ? t('PDF reader (PyMuPDF)')
    : sel.kind === 'reference-files' ? t('BibTeX / RIS files')
    : sel.kind === 'zotero' ? 'Zotero'
    : sel.id
  // The line under the sheet title: who makes it, or what DEIXIS uses it for.
  const sheetSub = !sel ? null
    : company ? t(company.maker)
    : sel.kind === 'provider' ? (providerUse[sel.id] ? t(providerUse[sel.id]) : providerRole(provider?.role))
    : sel.kind === 'zotero' ? t('Read-only collections')
    : sel.kind === 'semantic' ? t('Semantic search')
    : sel.kind === 'reference-files' ? t('Import a .bib or .ris file')
    : null
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
  const checkProps = { checking, start: runCheck }
  // The Codex login command comes from the backend, written for this computer's shell (the Sign in button is the main way).
  const codexLogin = data?.codex_login_command ?? null
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
    const ownRun = signInRuns[accountId] ?? null
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
        <CheckButton {...checkProps} id={key} label="Test the connection" run={() => refreshModel(accountId)} disabled={!model} quiet />
      </div>
      {ownRun?.state === 'waiting' && <p className="foot-note signin-wait" role="status">
        <span className="spin" aria-hidden />{t('A terminal window opened. Finish signing in there; this updates by itself.')}
        <button type="button" className="ghost" onClick={() => cancelSignIn(accountId)}>{t('Cancel')}</button>
      </p>}
      {ownRun && (ownRun.state === 'failed' || ownRun.state === 'timed_out') && ownRun.message && <p className="foot-note warn-t" role="alert">{t(ownRun.message)}</p>}
      {ownRun?.state === 'session_confirmed' && ownRun.message && <p className="foot-note" role="status">{t(ownRun.message)}</p>}
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
        {tool?.installed && tool.path && <dl className="local-tool-facts">
          <dt>{t('Path')}</dt><dd className="local-tool-path">{wrapPath(tool.path)}</dd>
          {tool.other_copies?.map(copy => <Fragment key={copy}><dt>{t('Also found')}</dt><dd className="local-tool-path">{wrapPath(copy)}</dd></Fragment>)}
        </dl>}
        {tool?.reason_code === 'not_runnable' && <p className="local-tool-note is-callout">{t('Found, but it did not run: its version check failed. Reinstall it, or remove the broken copy.')}</p>}
        {tool?.reason_code === 'unsupported_install' && <p className="local-tool-note is-callout">{t('This copy is installed in a way DEIXIS cannot start on Windows. Install it again with its official Windows installer.')}</p>}
        {tool?.installed && (tool.other_copies?.length ?? 0) > 0 && <p className="foot-note">{t('More than one copy is installed. DEIXIS uses the one shown under Path.')}</p>}
        {model.catalogue === 'fixed' && <p className="foot-note">{t('Gemini CLI cannot list its models, so this list is fixed in DEIXIS. A step that another model answers is stopped.')}</p>}
        <ModelCatalogue model={model} />
      </details>}
    </section>
  }
  // Models a failed research step took out of the lists (D59), each with why and a way to offer it again.
  const showAgain = (conn: string, id: string) => {
    setShowing(id)
    api.showHiddenModel(conn, id).then(result => {
      setData(current => current ? { ...current, models: { ...current.models, [conn]: result } } : current)
      toast('success', t('{model} is offered again.', { model: id }))
    }).catch((e: Error) => toast('error', e.message)).finally(() => setShowing(null))
  }
  const hiddenModels = (conn: string, hidden: NonNullable<ModelHealth['hidden_models']>) => <details className="way-more">
    <summary><ChevronRight size={14} aria-hidden />{t(hidden.length === 1 ? '1 model hidden after a step failed on it' : '{n} models hidden after a step failed on them', { n: hidden.length })}</summary>
    <p className="foot-note">{t('They stay out of the model lists for 30 days. Show one again if the provider serves it again.')}</p>
    <ul className="connection-models">{hidden.map(item => <li key={item.id}>
      <span className="connection-model-copy"><code className="model-id">{item.id}</code>
        <small>{item.reason === 'answered_as' ? withCode(t('Answered as {model}'), { model: item.answered_as ?? '' }) : t('The provider no longer serves it')}{item.at ? ` · ${day(item.at)}` : ''}</small></span>
      <span className="connection-model-meta"><button type="button" className="ghost" disabled={showing !== null} aria-busy={showing === item.id} onClick={() => showAgain(conn, item.id)}>
        {t('Show again')}</button></span>
    </li>)}</ul>
  </details>
  // The key way: the key field of the company's API connection, with that connection's own state.
  const keyWay = (c: Company) => {
    const way = c.key
    if (!way) return null
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
        removeEffect={effect} onSaved={() => reloadAfterModelKeyChange(way.conn)} />}
      {model?.hidden_models?.length ? hiddenModels(way.conn, model.hidden_models) : null}
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
  const localCheck = (conn: string | null) => Promise.all([...(conn ? [refreshModel(conn)] : []), loadTools(true, true), loadSemantic(true)])
  let body: ReactNode = null
  if (semanticRow) {
    const { isChosen, available, need, status } = semanticState(semanticRow)
    const key = semanticRow.apiKey
    const entry = key ? keyEntry(key.env) : undefined
    body = <>
      {semanticRow.desc && <p className="foot-note is-ink">{semanticRow.desc}</p>}
      {key && <section className={`way ${entry?.configured ? 'is-on' : ''}`} aria-label={t('With an API key')}>
        {wayHead(t('With an API key'), !credentials ? loading : entry?.configured ? ['ok', t('Ready')] : ['no', t('No key entered')])}
        <p className="way-desc">{linkify(t('Get the key at {site}.', { site: key.site }))}</p>
        {credentials && <KeyField key={key.env} env={key.env} entry={entry} keychain={credentials.keychain} label={t('Key')} service={key.service}
          removeEffect={key.env === 'VOYAGE_API_KEY' ? t('Semantic search and reranking with Voyage stop until you add a key again.')
            : key.env === 'COHERE_API_KEY' ? t('Semantic search and reranking with Cohere stop until you add a key again.')
            : key.env === 'OPENAI_API_KEY' ? t('Research steps with this key, and semantic search with OpenAI, stop until a new key is added.')
            : t('Research steps with this key, and semantic search with Gemini, stop until a new key is added.')}
          onSaved={() => key.conn ? reloadAfterModelKeyChange(key.conn) : reloadAfterKeyChange()} />}
      </section>}
      {semanticRow.body}
      <section className={`way ${isChosen && !need ? 'is-on' : ''}`} aria-label={t('Semantic search')}>
        {wayHead(t('Semantic search'), [isChosen && !need ? 'ok' : 'no', status])}
        <p className="way-desc">{privacyOf(semanticRow.id === 'server' ? 'ollama' : semanticRow.providers[0])}</p>
        {semanticRow.id === 'server' && isChosen && serverChoices.length > 0 && <select className="select semantic-model" aria-label={t('Embedding model')} disabled={saving} value={`${chosen?.provider}|${chosen?.model ?? ''}`}
          onChange={e => { const [p, ...m] = e.target.value.split('|'); chooseSemantic(p as SemanticSearchProvider, m.join('|')) }}>
          {serverChoices.map(c => <option key={`${c.provider}|${c.model}`} value={`${c.provider}|${c.model}`}>{c.label}</option>)}
        </select>}
        {(!isChosen || (semantic && !semantic.explicit)) && <div className="actions">
          <button type="button" className="btn-pri" disabled={!available || saving} onClick={() => pickSemantic(semanticRow)}>
            {saving ? <span className="spin" aria-hidden /> : <CircleCheck aria-hidden />}{semanticRow.id === 'off' ? t('Turn semantic search off') : t('Use for semantic search')}</button>
        </div>}
      </section>
    </>
  } else if (company) {
    const ways = company.keyFirst
      ? [keyWay(company), company.account && accountWay(company)]
      : [company.account ? accountWay(company) : company.soon ? soonWay(company.soon) : null, keyWay(company)]
    body = <>
      <p className="foot-note is-ink">{t(company.intro ?? (company.account && company.key ? 'Either way is enough. If you have a subscription, signing in with your account is the easiest.'
        : company.account ? 'This model connects with your account only.' : 'This model connects with an API key only for now.'))}</p>
      {ways}
      {company.account && company.key && <p className="foot-note">{t('If both are connected, each appears as its own choice in the model lists. A research uses the one you choose; DEIXIS does not switch between them by itself.')}</p>}
    </>
  } else if (sel?.kind === 'local' && sel.id === 'ollama') {
    const model = data?.models.ollama
    const tool = toolOf('ollama')
    // One status line (address and version beside it), the embedding choice and the installed models; the path, role and
    // the fixed address field stay out, since none of them is something to act on here.
    const version = tool?.version?.match(/\d+(\.\d+)+/)?.[0]
    const address = tool?.running ? tool.endpoint?.replace(/^https?:\/\//, '') : undefined
    body = <>
      <section className="server-status" aria-label={t('Status')}>
        <div className="server-status-head">
          {dmeta('local:ollama', model ? modelStatus(model) : data ? unknown : loading, undefined, model && !model.ready ? healthReasonText(model) : undefined)}
          <CheckButton {...checkProps} id="local:ollama" label="Test" run={() => localCheck(model ? 'ollama' : null)} quiet />
        </div>
        {(address || version) && <dl className="server-facts">
          {address && <div><dt>{t('Address')}</dt><dd><code>{address}</code></dd></div>}
          {version && <div><dt>{t('Version')}</dt><dd>{version}</dd></div>}
        </dl>}
      </section>
      <p className="foot-note">{t(tool && !tool.installed ? 'Ollama is not installed on this computer.' : tool && !tool.running ? 'Open the Ollama app or run `ollama serve`.' : 'No key is needed; DEIXIS uses Ollama on this computer.')}</p>
      {tool?.running && <section className="server-block" aria-label="Ollama">
        <LocalModels tool={tool} dark={dark} memoryGb={machine?.memory_gb ?? null} onChanged={reloadTools} onDone={() => { void localCheck('ollama') }} />
      </section>}
      {tool && !tool.running && <LocalAppInstall tool={tool} dark={dark} onChanged={reloadTools} onDone={() => { void localCheck('ollama') }} />}
    </>
  } else if (sel?.kind === 'local' && sel.id === 'lm_studio') {
    const status: [Tone, string] = lmStudioInUse && localServer ? modelStatus(localServer) : !lmStudio ? (toolsError ? unknown : loading)
      : lmStudio.running ? ['no', t('Running')] : lmStudio.installed ? ['no', t('Not running')] : ['no', t('Not installed')]
    const address = lmStudio?.running ? lmStudio.endpoint?.replace(/^https?:\/\//, '') : undefined
    // `lms --version` names a CLI commit, not the app's version, so only a version number is shown.
    const version = lmStudio?.version?.match(/\d+(\.\d+)+/)?.[0]
    body = <>
      <section className="server-status" aria-label={t('Status')}>
        <div className="server-status-head">
          {dmeta('local:lm_studio', status, undefined, lmStudioInUse && localServer && !localServer.ready ? healthReasonText(localServer) : undefined)}
          <CheckButton {...checkProps} id="local:lm_studio" label="Test" run={() => localCheck(lmStudioInUse ? 'local_server' : null)} quiet />
        </div>
        {lmStudio?.installed && <dl className="server-facts">
          {address && <div><dt>{t('Address')}</dt><dd><code>{address}</code></dd></div>}
          {version && <div><dt>{t('Version')}</dt><dd>{version}</dd></div>}
          <div><dt>{t('Research steps')}</dt><dd>{t(lmStudioInUse ? 'In use' : 'Not in use')}</dd></div>
        </dl>}
      </section>
      <p className="foot-note is-ink">{t('LM Studio runs models on this computer. Research steps reach it through its local server address; semantic search can use one of its embedding models.')}</p>
      {serverError && <Notice tone="error"><p>{serverError}</p></Notice>}
      {lmStudioUrl && lmStudio?.installed && !lmStudioInUse && <div className="acts">
        <button type="button" className="btn-pri" disabled={serverBusy || !lmStudio?.running} onClick={() => saveLocalServer(lmStudioUrl)}
          title={lmStudio?.running ? undefined : t('Start LM Studio’s local server first')}>{t('Use for research steps')}</button>
      </div>}
      {lmStudio?.running && <section className="server-block" aria-label="LM Studio">
        <LocalModels tool={lmStudio} dark={dark} memoryGb={machine?.memory_gb ?? null} onChanged={reloadTools} onDone={() => { void localCheck(lmStudioInUse ? 'local_server' : null) }} />
      </section>}
      {lmStudio && !lmStudio.running && <LocalAppInstall tool={lmStudio} dark={dark} onChanged={reloadTools} onDone={() => { void localCheck(lmStudioInUse ? 'local_server' : null) }} />}
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
          {saved && <CheckButton {...checkProps} id="local:local_server" label="Test" run={() => refreshModel('local_server')} disabled={serverBusy} quiet />}
        </div>
      </form>
      {localServer && saved && <ModelCatalogue model={localServer} />}
    </>
  } else if (sel?.kind === 'provider' && provider) {
    const env = providerKeyEnv[provider.id]
    const [tone, status] = providerStatus(provider.access_mode, provider.key_broken)
    const key = `provider:${provider.id}`
    const keyless = provider.access_mode === 'keyless'
    const test = keyless && checking !== key && checked[key] && !checkFailed[key] ? providerTests[provider.id] : undefined
    const id = provider.id
    // The status chip already says "No key needed"; the lead only adds what the chip cannot.
    const lead = provider.id === 'openalex' ? linkify(t('Works without a key. A free key from openalex.org gives DEIXIS its own daily budget.'))
      : !env ? (MAILTO_PROVIDERS.has(provider.id) ? t('No key needed. DEIXIS adds your contact email to its requests, as the service asks.') : null)
      : t(provider.note)
    body = <>
      {dmeta(key, [tone, status], test && <span className={`status-chip ${test.answered && (test.http_status ?? 0) < 300 ? '' : 'is-warning'}`}>{providerAnswer(test)}</span>)}
      {lead && <p className="sheet-lead">{lead}</p>}
      {env && credentials && <section className="sheet-card">
        <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain} service={providerNames[provider.id] ?? provider.id}
          label={t(provider.id === 'openalex' ? 'API key (optional, free from openalex.org)' : 'API key')}
          removeEffect={t('Requests that need this key stop until you add one again.')} onSaved={reloadAfterKeyChange} />
        {providerKeySignup[id] && <p className="sheet-card-foot key-signup">{linkify(t(providerKeySignup[id].steps))} <a href={providerKeySignup[id].url} target="_blank" rel="noopener noreferrer">{t('Get a key')}<ArrowUpRight aria-hidden /></a></p>}
      </section>}
      {env && !credentials && providerKeySignup[id] && <p className="foot-note key-signup">{linkify(t(providerKeySignup[id].steps))} <a href={providerKeySignup[id].url} target="_blank" rel="noopener noreferrer">{t('Get a key')}</a></p>}
      {env && credentials && !keyEntry(env)?.configured && providerNoKey[provider.id] && <Notice tone="attention">{t(providerNoKey[provider.id])}</Notice>}
      {keyless && <section className="sheet-card">
        <p className="sheet-card-text">{t('Test sends one request to {name} without a key and shows how it answered.', { name: providerNames[id] ?? id })}</p>
        <div className="acts"><CheckButton {...checkProps} id={key} label="Test" run={() => api.testProvider(id).then(result => { setProviderTests(old => ({ ...old, [id]: result })); return result })} /></div>
        {test && !test.contact_email_sent && <p className="foot-note">{t('Sent without a contact email; none is set in Profile.')}</p>}
      </section>}
      {MAILTO_PROVIDERS.has(provider.id) && <dl className="sheet-facts">
        <div><dt>{t('Contact email')}</dt><dd><a href="#/settings/profile">{t('Set in Profile')}</a></dd></div>
      </dl>}
    </>
  } else if (sel?.kind === 'equation-reader') {
    body = <>
      <div className="tool-status">{dmeta('equation-reader', readerStatus())}<CheckButton {...checkProps} id="equation-reader" label="Find it on this computer" run={() => loadReader(true)} quiet /></div>
      {reader && <EquationReaderDetails reader={reader} dark={dark} onChanged={reloadReader} />}
    </>
  } else if (sel?.kind === 'mathpix') {
    body = <>
      <div className="tool-status">{dmeta('mathpix', mathpixStatus())}</div>
      {mathpix && credentials && <MathpixDetails mathpix={mathpix} keychain={credentials.keychain} dark={dark} onKeychainChanged={loadCredentials} onChanged={next => { if (next) setMathpix(next); else void loadMathpix() }} />}
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
      <p className="sheet-lead">{t('Import a collection from Add sources on the home page or from a research’s Sources panel. Your Zotero library is never changed.')}</p>
      <section className="zotero-route sheet-card">
        <div className="zotero-route-head"><span className="route-ico" aria-hidden><Laptop /></span><h3>{t('This computer')}</h3>{zotero && <span className={`status-chip is-status ${zotero.installed && zotero.running && zotero.local_api ? '' : 'is-configured'}`}>
          {t(!zotero.installed ? 'Not installed' : !zotero.running ? 'Not running' : zotero.local_api ? 'Local API on' : 'Local API off')}</span>}</div>
        {zotero && <LocalToolDetails tool={zotero} dark={dark} onChanged={reloadTools} refresh={false} chip={false} />}
        <div className="acts"><CheckButton {...checkProps} id="zotero" label="Find it on this computer" run={() => loadTools(true, true)} quiet /></div>
      </section>
      {credentials && <section className="zotero-route sheet-card">
        <div className="zotero-route-head"><span className="route-ico" aria-hidden><Cloud /></span><h3>zotero.org</h3>{zotero && <span className={`status-chip is-status ${zotero.web_configured ? '' : 'is-configured'}`}>{t(zotero.web_configured ? 'Key and user ID saved' : 'Not set up')}</span>}</div>
        <p className="sheet-card-text">{linkify(t('To import from zotero.org, create a read-only key at zotero.org/settings/keys. Your user ID is shown on the same page.'))}</p>
        {(['ZOTERO_API_KEY', 'ZOTERO_LIBRARY_ID'] as const).map(env => <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain}
          plain={env === 'ZOTERO_LIBRARY_ID'} note={env === 'ZOTERO_LIBRARY_ID'} label={t(env === 'ZOTERO_API_KEY' ? 'zotero.org API key' : 'zotero.org user ID')} service="zotero.org"
          removeEffect={t('Importing from zotero.org stops until you add it again.')} onSaved={() => { reloadAfterKeyChange(); void reloadTools() }} />)}
      </section>}
    </>
  } else if (sel?.kind === 'reference-files') {
    body = <>
      <p className="sheet-lead">{t('Adds the entries of a .bib or .ris file to the Library.')}</p>
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
      <h2 data-panel="general">{t('This computer')}</h2>
      <div className="machine-card" data-group="machine" data-panel="general">
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
    <h2 data-panel="search">{t('Semantic search')}</h2>
    <p className="foot-note" data-panel="search">{t('Ranks search results by meaning, not only by shared words. Changing the provider scores the passages again; earlier scores are kept.')}</p>
    {semError && <Notice tone="error" panel="search">{semError}</Notice>}
    {semantic?.builtin_model_changed && <Notice tone="attention" panel="search">{t('The built-in model chosen earlier is not available in this version of DEIXIS, so semantic search does not run with it. Pick a built-in model below; DEIXIS does not switch to another one by itself. Scores stored with the earlier model are kept but not reused.')}</Notice>}
    <div className="choice-groups" data-panel="search" data-group="semantic" aria-busy={saving || undefined}>
      {([[true, t('Local models')], [false, t('API models')], [null, null]] as const).map(([local, head]) => <Fragment key={String(local)}>
        {head && <h3 className="choice-head">{head}</h3>}
        {local === true && builtin && <BuiltinCatalog builtin={builtin} kind="embedding" inUse={builtinChosen} onOpen={setBuiltinSheet} />}
        {semanticRows.some(row => row.local === local) && <div className={`co-grid ${local === null ? 'choice-off' : ''}`}>{semanticRows.filter(row => row.local === local).map(row => {
          const { isChosen, need, status } = semanticState(row)
          return <CompanyCard key={row.id} mark={companyMark(undefined, undefined, settingsIcon(row.id))} name={row.label}
            maker={row.local === null || row.id === 'server' ? row.model ?? '' : <code className="model-id">{row.model}</code>}
            ready={isChosen && !need} status={status} active={isChosen} compact onClick={() => show({ kind: 'semantic', id: row.id })} />
        })}</div>}
        {local === true && builtin && <BuiltinLegacy builtin={builtin} dark={dark} onChanged={builtinChanged} />}
      </Fragment>)}
    </div>
    {builtin && <BuiltinModelSheet builtin={builtin} model={builtinModel} dark={dark} onClose={() => setBuiltinSheet(null)} onChanged={builtinChanged}
      use={builtinModel && <section className={`way ${builtinModelChosen && builtinReady ? 'is-on' : ''}`} aria-label={t('Semantic search')}>
        {wayHead(t('Semantic search'), [builtinModelChosen && builtinReady ? 'ok' : 'no', builtinModelChosen ? (builtinReady ? t('In use') : t(builtinModelOption?.reason ?? 'Not downloaded')) : builtinReady ? t('Not in use') : t(builtinModelOption?.reason ?? 'Not downloaded')])}
        <p className="way-desc">{privacyOf('builtin')}</p>
        {(!builtinModelChosen || (semantic && !semantic.explicit)) && <div className="actions">
          <button type="button" className="btn-pri" disabled={!builtinReady || saving} aria-describedby={!builtinReady ? 'builtin-semantic-why' : undefined} onClick={() => chooseSemantic('builtin', builtinModel.id)}>
            {saving ? <span className="spin" aria-hidden /> : <CircleCheck aria-hidden />}{t('Use for semantic search')}</button>
          {!builtinReady && <span className="sr-only" id="builtin-semantic-why">{t('Download the model first.')}</span>}
        </div>}
      </section>} />}
    {privacy && <p className="foot-note semantic-privacy" data-panel="search">{privacy}</p>}
    <RerankingSettings dark={dark} builtin={builtin} onBuiltinChanged={builtinChanged} keyField={(env, service) => credentials ? <KeyField key={env} env={env} entry={keyEntry(env)} keychain={credentials.keychain} label={t('Key')} service={service}
      removeEffect={env === 'VOYAGE_API_KEY' ? t('Semantic search and reranking with Voyage stop until you add a key again.')
        : env === 'COHERE_API_KEY' ? t('Semantic search and reranking with Cohere stop until you add a key again.') : t('Reranking with {service} stops until you add a key again.', { service })}
      onSaved={reloadAfterKeyChange} /> : null} refresh={`${builtin?.models.map(m => m.state).join(',') ?? ''}|${['VOYAGE_API_KEY', 'COHERE_API_KEY', 'JINA_API_KEY', 'ZEROENTROPY_API_KEY'].map(env => keyEntry(env)?.configured ?? '').join('|')}`} />

    <section className="doc-readers" data-panel="documents" aria-labelledby="document-reading">
      <div className="co-group-head"><h2 id="document-reading">{t('Document reading')}</h2><p className="co-note">{t('Tools that take the text out of PDFs.')}</p></div>
      <ul className="doc-list" data-group="documents">{docRows.map(row => {
        const [tone, status] = row.status
        return <li key={row.kind}><button type="button" className={isActive(row.kind, row.id) ? 'on' : ''} onClick={() => show({ kind: row.kind, id: row.id })}>
          {settingsIcon(row.kind === 'ocr-tool' ? 'ocr' : row.id)}<span><b>{t(row.name)}</b><small>{t(row.what)}</small></span><span className={`st ${tone}`}>{status}</span>
        </button></li>
      })}</ul>
    </section>

    {access}

    <h2 data-panel="sources">{t('Scholarly sources')}</h2>
    <div className="grid3" data-group="sources" data-panel="sources">{providers.map(p => tile(p.id, 'provider', p.id, providerNames[p.id] ?? p.id, providerUse[p.id] ? t(providerUse[p.id]) : providerRole(p.role), providerStatus(p.access_mode, p.key_broken)))}</div>
    <p className="foot-note sources-note" data-panel="sources">{t('Searches run on OpenAlex, joined by Semantic Scholar in Detailed mode. The other sources fill in abstracts, check records or find PDFs.')}</p>

    <h2 data-panel="sources">{t('Reference managers')}</h2>
    <div className="grid3" data-group="references" data-panel="sources">
      {tile('zotero', 'zotero', 'zotero', 'Zotero', t('Read-only collections'), zoteroStatus())}
      {tile('reference-files', 'reference-files', 'files', t('BibTeX / RIS files'), t('Import a .bib or .ris file'), ['ok', t('Available')])}
    </div>

    <Sheet open={open && !gone} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet connection-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader className="sheet-head">
          {sheetIcon && <span className="sheet-mark" aria-hidden>{sheetIcon}</span>}
          <div className="sheet-head-text">
            <SheetTitle>{name}</SheetTitle>
            <SheetDescription className={sheetSub ? '' : 'sr-only'}>{sheetSub ?? t('{name} details', { name })}</SheetDescription>
          </div>
        </SheetHeader>
        <div className="connection-body mk pad detail">{body}</div>
      </SheetContent>
    </Sheet>
  </>
}
