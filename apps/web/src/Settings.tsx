import { useCallback, useEffect, useRef, useState } from 'react'
import { Info, RotateCw } from 'lucide-react'
import { api, shellApi, usageApi, type ContactEmailSetting, type Profile, type Connections, type InstitutionalAccess, type ModelRole, type OpenAlexBudgetToday, type ProxySettings, type RoleModelSetting, type Usage, type UsageRole } from './api'
import { connectionModels, modelKey, type ConnectionModel } from './Home'
import { defaultEffort, exposesEffortControl } from './modelEffort'
import { ConnectionsTab } from './Connections'
import { useToast } from './Toast'
import { t, uiLocale, type UiLanguage } from './i18n'
import { connectionName, reasoningLabel } from './labels'
import { Notice } from './Notice'
import './research/kit.css'
import './Settings.css'

const NO_DEFAULT = '__none'
// The mockup's order and words (plan ST3); what each role does is the same in the composer's model menu.
const ROLES: { role: ModelRole; label: string; desc: string }[] = [
  { role: 'literature', label: 'Literature', desc: 'Plans searches and screens abstracts' },
  { role: 'answer', label: 'Answer', desc: 'Writes the source-linked answer' },
  { role: 'reviewer', label: 'Reviewer', desc: 'Checks each claim against its passages' },
]
const clock = (iso: string) => new Date(iso).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })

/** The institutional access state the sidebar's access line shows, read and tested by the app shell (App.tsx), so the
 *  page and the line never disagree and never run two tests at once. Two separate facts (plan §2.3): the proxy host
 *  answered or not, and Scopus grants its full view on this network or not. */
/** The name in the sidebar: typed here, else the OS account's. It stays on this computer. */
function ProfileNameRow({ onProfile }: { onProfile: (profile: Profile) => void }) {
  const [stored, setStored] = useState<Profile | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const toast = useToast()
  useEffect(() => {
    let live = true
    shellApi.profile().then(value => { if (live) { setStored(value); setDraft(value.name_source === 'setting' ? value.full_name : '') } }, (e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [])
  const current = stored?.name_source === 'setting' ? stored.full_name : ''
  const changed = stored !== null && draft.trim() !== current
  const save = () => {
    setBusy(true); setError('')
    shellApi.saveProfileName(draft.trim() || null).then(value => {
      setStored(value); setDraft(value.name_source === 'setting' ? value.full_name : ''); onProfile(value)
      toast('success', t(value.name_source === 'setting' ? 'Name saved.' : 'Name reset to the computer account.'))
    }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  return <form onSubmit={e => { e.preventDefault(); if (changed) save() }}>
    <b><label htmlFor="profile-name">{t('Name')}</label></b>
    <p>{t('Shown in the sidebar. It stays on this computer.')}{error && <span className="key-form-error" role="alert"> {error}</span>}</p>
    <input id="profile-name" className="field" type="text" autoComplete="name" maxLength={80} value={draft} disabled={stored === null || busy}
      placeholder={stored?.account_name || t('Your name')} onChange={e => { setDraft(e.target.value); setError('') }} />
    <button type="submit" className="ghost" disabled={busy || !changed}>{t(busy ? 'Saving…' : 'Save')}</button>
  </form>
}

/** The contact email (F15): sent as `mailto` with OpenAlex and Crossref requests; the setting wins over DEIXIS_CONTACT_EMAIL. */
function ContactEmailRow() {
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
  const changed = stored !== null && draft.trim() !== (stored.email ?? '')
  const save = () => {
    setBusy(true); setError('')
    shellApi.saveContactEmail(draft.trim() || null).then(value => {
      setStored(value); setDraft(value.email ?? '')
      toast('success', t(value.email ? 'Contact email saved.' : 'Contact email removed.'))
    }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  return <form onSubmit={e => { e.preventDefault(); if (changed) save() }}>
    <b><label htmlFor="contact-email">{t('Email')}</label></b>
    <p>{t('Sent only to OpenAlex and Crossref, which answer faster and more steadily when a request carries an email.')}
      {error && <span className="key-form-error" role="alert"> {error}</span>}</p>
    <input id="contact-email" className="field" type="email" autoComplete="email" value={draft} disabled={stored === null || busy} placeholder="you@university.edu"
      onChange={e => { setDraft(e.target.value); setError('') }} />
    <button type="submit" className="ghost" disabled={busy || !changed}>{t(busy ? 'Saving…' : 'Save')}</button>
    {stored && !stored.email && <Notice tone="attention">{stored.environment_set ? t('While this field is empty, DEIXIS_CONTACT_EMAIL from the environment is sent.') : t('Without an email, OpenAlex and Crossref answer more slowly at busy times. Searches still run.')}</Notice>}
  </form>
}

export type AccessControl = {
  proxy: ProxySettings | null
  readFailed: boolean
  testing: boolean
  /** The last test request itself failed (no answer from DEIXIS) for this address. */
  testFailed: boolean
  scopus: InstitutionalAccess['status'] | null
  /** A fresh test after any running one; rejects when the request fails. */
  test: (address?: string) => Promise<ProxySettings | null>
  /** Saves the address ('' removes it) under the same version as reads and tests; rejects when the save fails. */
  save: (address: string) => Promise<void>
  reload: () => void
}

export function SettingsPage({ dark, section, language, onLanguage, onProfile, access }: {
  dark: boolean; section?: 'connections' | 'access' | 'openalex' | 'profile'; language: UiLanguage; onLanguage: (language: UiLanguage) => void
  onProfile: (profile: Profile) => void; access: AccessControl
}) {
  const toast = useToast()
  const [models, setModels] = useState<ConnectionModel[] | null>(null)
  const [anyReady, setAnyReady] = useState<boolean | null>(null)
  const [defaults, setDefaults] = useState<Record<ModelRole, RoleModelSetting> | null>(null)
  const [savingRole, setSavingRole] = useState<ModelRole | null>(null)
  const [error, setError] = useState('')

  // The model choices come from the connections answer the sections below read, so a key change or a connection test
  // there updates them too (the sections show their own read error).
  const onConnections = useCallback((result: Connections) => { setModels(connectionModels(result)); setAnyReady(Object.values(result.models).some(h => h.ready)) }, [])
  useEffect(() => {
    api.settings().then(setDefaults).catch((e: Error) => setError(t('The default models could not be read: {message}', { message: e.message })))
  }, [])

  // `#/settings/connections` opens the page at "On this computer", `#/settings/access` at "Institutional access" (ST1);
  // `#/settings/openalex` opens the OpenAlex sheet (R19's "Add an OpenAlex key"), which takes the focus itself.
  const scrolled = useRef(false)
  useEffect(() => {
    if (!section || section === 'openalex' || scrolled.current || !defaults) return
    scrolled.current = true
    const target = document.getElementById(section === 'access' ? 'institutional-access' : section === 'profile' ? 'profile' : 'on-this-computer')
    target?.scrollIntoView({ block: 'start' })
    target?.focus({ preventScroll: true })
  }, [section, defaults])

  // One save per role at a time; the role's controls stay locked until the server answers.
  function save(role: ModelRole, next: RoleModelSetting) {
    if (savingRole) return
    const label = t(ROLES.find(r => r.role === role)!.label).toLocaleLowerCase(uiLocale())
    setSavingRole(role)
    api.saveModelDefault(role, next).then(saved => {
      setDefaults(old => old && { ...old, [role]: saved[role] ?? next })
      toast('success', saved[role]?.model ? t('Default {role} model: {model}', { role: label, model: saved[role]!.model! }) : t('No default {role} model', { role: label }))
    }).catch((e: Error) => toast('error', t('Could not save the default: {message}', { message: e.message })))
      .finally(() => setSavingRole(null))
  }

  return <section className="settings-page mk">
    <h1 tabIndex={-1}>{t('Settings')}</h1>
    {error && <Notice tone="error">{error}</Notice>}
    {anyReady === false && <div className="notice info"><Info aria-hidden /><span>{t('Connect Codex CLI or Claude Code below to start.')}</span></div>}

    <h2 id="profile" tabIndex={-1}>{t('Profile')}</h2>
    <div className="rows set-profile">
      <ProfileNameRow onProfile={onProfile} />
      <ContactEmailRow />
    </div>

    <h2>{t('Default models')}</h2>
    <p className="foot-note set-roles-note">{t('Defaults apply to new researches. Each research keeps the models it was created with.')}</p>
    <div className="rows set-roles">
      {ROLES.map(({ role, label, desc }) => {
        const current = defaults?.[role]
        const list = models ?? []
        const value = current?.model ? modelKey(current.model_connection, current.model) : NO_DEFAULT
        const picked = list.find(m => m.id === value)
        const efforts = picked && exposesEffortControl(picked) ? picked.reasoning_efforts ?? [] : []
        const locked = !models || !defaults || !list.length || savingRole !== null
        const groups = [...new Set(list.map(m => m.connection))]
        return <div key={role}>
          <b>{t(label)}</b>
          <p>{t(desc)}</p>
          <select className="select" aria-label={t('{role} model', { role: t(label) })} disabled={locked} value={!list.length ? NO_DEFAULT : value}
            onChange={e => {
              if (!current) return
              const m = list.find(x => x.id === e.target.value)
              save(role, m ? { model_connection: m.connection, model: m.model, reasoning_effort: defaultEffort(list, m.id) }
                : { model_connection: current.model_connection, model: null, reasoning_effort: null })
            }}>
            {!list.length
              ? <option value={NO_DEFAULT}>{t(models ? 'Not connected' : 'Checking…')}</option>
              : <>
                <option value={NO_DEFAULT}>{t(role === 'reviewer' ? 'No default reviewer' : 'No default')}</option>
                {current?.model && !picked && <option value={value}>{t('{model} · not listed now', { model: current.model })}</option>}
                {groups.map(connection => <optgroup key={connection} label={connectionName(connection)}>
                  {list.filter(m => m.connection === connection).map(m => <option key={m.id} value={m.id}>{m.display_name}</option>)}
                </optgroup>)}
              </>}
          </select>
          <select className="select" aria-label={t('{role} effort', { role: t(label) })} disabled={locked || !efforts.length}
            value={efforts.some(e => e.id === current?.reasoning_effort) ? current!.reasoning_effort! : ''}
            onChange={e => current && save(role, { ...current, reasoning_effort: e.target.value || null })}>
            {!efforts.length && <option value="">{t(picked ? 'No thinking levels' : '—')}</option>}
            {efforts.length > 0 && <option value="">{t('Model default')}</option>}
            {efforts.map(level => <option key={level.id} value={level.id}>{reasoningLabel(level.id)}</option>)}
          </select>
        </div>
      })}
    </div>

    <ConnectionsTab dark={dark} access={<InstitutionalAccessBlock access={access} />} onConnections={onConnections} openProvider={section === 'openalex' ? 'openalex' : undefined} />

    <UsageThisMonth />

    <h2>{t('Language')}</h2>
    <div className="rows set-lang">
      <div>
        <b>{t('Interface')}</b>
        <p>{t('Research content (questions, answers, quotes) stays in the language it was written in.')}</p>
        <span className="lang" role="group" aria-label={t('Interface language')}>
          <button type="button" className={language === 'en' ? 'on' : ''} aria-pressed={language === 'en'} lang="en" onClick={() => onLanguage('en')}>English</button>
          <button type="button" className={language === 'tr' ? 'on' : ''} aria-pressed={language === 'tr'} lang="tr" onClick={() => onLanguage('tr')}>Türkçe</button>
        </span>
      </div>
    </div>

    <footer className="settings-footer"><span>{t('© 2026 DEIXIS · Designed & built by')} <a href="https://huguryildiz.com" target="_blank" rel="noopener noreferrer">Hüseyin Uğur Yıldız</a><a className="footer-github" href="https://github.com/huguryildiz/DEIXIS" target="_blank" rel="noopener noreferrer" aria-label={t('DEIXIS on GitHub')} title={t('DEIXIS on GitHub')}><svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z" /></svg></a></span></footer>
  </section>
}

// Institutional access (plan ST6, §2.3). The proxy address is used only for links the person opens in the browser; Test
// saves a changed address, then asks the proxy host once (never an article). Its line and the Scopus line are separate
// measured facts.
function InstitutionalAccessBlock({ access }: { access: AccessControl }) {
  const toast = useToast()
  const saved = access.proxy?.address ?? null
  const [draft, setDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const field = draft ?? saved ?? ''
  const test = async () => {
    const address = field.trim()
    if (!address || busy || access.testing) return
    setBusy(true); setMessage('')
    try {
      if (address !== (saved ?? '')) {
        try { await access.save(address) } catch (e) { setMessage(t('Not saved: {message}', { message: (e as Error).message })); return }
        setDraft(null)
      }
      try { await access.test(address) } catch (e) { setMessage(t('The check could not run: {message}', { message: (e as Error).message })) }
    } finally { setBusy(false); access.reload() }
  }
  const remove = () => {
    if (busy) return
    setBusy(true); setMessage('')
    access.save('').then(() => { setDraft(null); toast('success', t('Proxy address removed. Links open directly.')) })
      .catch((e: Error) => setMessage(t('Not removed: {message}', { message: e.message })))
      .finally(() => { setBusy(false); access.reload() })
  }

  const p = access.proxy
  const test_ = p?.test
  const current = !!test_ && p!.test_is_current
  let line: { tone: 'ok' | 'no' | 'warn' | 'checking'; pill: string; text: string }
  if (access.readFailed) line = { tone: 'no', pill: t('Proxy check could not run'), text: t('The proxy setting could not be read.') }
  else if (!p) line = { tone: 'checking', pill: '', text: t('Checking…') }
  else if (!p.address) line = { tone: 'no', pill: t('Not set up'), text: t('Without a proxy, publisher links open directly.') }
  else if (busy || access.testing) line = { tone: 'checking', pill: '', text: t('Checking: asking the proxy host…') }
  else if (message) line = { tone: 'no', pill: t('Proxy check could not run'), text: message }
  else if (access.testFailed && !current) line = { tone: 'no', pill: t('Proxy check could not run'), text: t('The last check got no answer from DEIXIS. Test again.') }
  else if (!test_ || !current) line = { tone: 'no', pill: t('Not checked'), text: test_?.route_changed_during_test ? t('The network changed during the last check. Test again.') : test_ ? t('The address or the network changed since the last check.') : t('Not checked yet.') }
  else if (test_.proxy_reachable) line = { tone: 'ok', pill: t('Proxy reachable'), text: t('Article access not checked. The proxy host answered with HTTP {status} at {time}.', { status: test_.proxy_http_status ?? '?', time: clock(test_.tested_at) }) }
  else if (test_.proxy_error === 'blocked_url') line = { tone: 'no', pill: t('Proxy not asked'), text: t('The address was refused before any request was sent: {detail}', { detail: test_.proxy_error_detail ?? '' }) }
  else line = { tone: 'warn', pill: t('Proxy did not answer'), text: `${test_.proxy_error === 'unresolved' ? t('Its host name does not resolve on this network.') : test_.proxy_error === 'timeout' ? t('No answer within 10 seconds.') : t('The request failed ({detail}).', { detail: test_.proxy_error_detail ?? test_.proxy_error ?? '' })} ${t('Checked at {time}.', { time: clock(test_.tested_at) })}` }
  const scopus: { tone: 'ok' | 'no' | 'warn'; pill: string; text: string } | null =
    access.scopus === 'institutional' ? { tone: 'ok', pill: t('Scopus full view confirmed'), text: t('Scopus grants its full view on this network.') }
    : access.scopus === 'none' ? { tone: 'warn', pill: t('Scopus full view not confirmed'), text: t('Scopus did not grant its full view on this network.') }
    : access.scopus === 'unknown' ? { tone: 'no', pill: t('Scopus check could not run'), text: t('Scopus gave no usable answer.') }
    : access.scopus === 'not_checked' ? { tone: 'no', pill: t('Scopus check could not run'), text: t('No Scopus key is set.') }
    : null

  return <>
    <h2 id="institutional-access" tabIndex={-1}>{t('Institutional access')}</h2>
    <div className="rows"><div className="proxy">
      <form className="lbl" onSubmit={e => { e.preventDefault(); void test() }}>
        <label htmlFor="proxy-address">{t('Proxy address (EZproxy or OpenAthens prefix)')}</label>
        <div className="row">
          <input id="proxy-address" className="field" type="url" inputMode="url" spellCheck={false} autoComplete="off" value={field} disabled={!p || busy}
            placeholder="https://login.ezproxy.your-library.edu/login?url=" onChange={e => { setDraft(e.target.value); setMessage('') }} />
          <button type="submit" className="ghost" disabled={!p || busy || access.testing || !field.trim()}>{busy || access.testing ? <span className="spin" aria-hidden /> : <RotateCw aria-hidden />}{t('Test')}</button>
          {saved && <button type="button" className="ghost" disabled={busy} onClick={remove}>{t('Remove')}</button>}
        </div>
      </form>
      <div className="row proxy-state" role="status">
        {line.tone === 'checking' ? <span className="spin" aria-hidden /> : <span className={`st ${line.tone}`}>{line.pill}</span>}
        <span>{line.text}</span>
        {(access.readFailed) && <button type="button" className="link" onClick={access.reload}>{t('Try again')}</button>}
      </div>
      {scopus && <div className="row proxy-state proxy-scopus"><span className={`st ${scopus.tone}`}>{scopus.pill}</span><span>{scopus.text}</span></div>}
      <p className="foot-note">{t('Publisher links open through this address in your browser, and DEIXIS never stores your library password. Test saves the address and checks once that the proxy answers; it does not open an article.')}</p>
    </div></div>
  </>
}

// Usage this month (plan ST9, F7/F8): model calls per Settings role, counted from the stored model sessions of this
// calendar month; the bar is the role's share of those calls. OpenAlex's budget today is its last stored response,
// shown with that response's time. A figure that could not be read is "not known", never 0.
function UsageThisMonth() {
  const [month, setMonth] = useState<{ value: Usage | null; failed: string }>({ value: null, failed: '' })
  const [budget, setBudget] = useState<{ value: OpenAlexBudgetToday | null; failed: string }>({ value: null, failed: '' })
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)
  const read = (again = true) => {
    const n = ++seq.current
    if (again) setLoading(true)
    void Promise.allSettled([usageApi.usageThisMonth(), usageApi.openAlexBudgetToday()]).then(([u, b]) => {
      if (n !== seq.current) return
      setMonth(u.status === 'fulfilled' ? { value: u.value, failed: '' } : old => ({ value: old.value, failed: (u.reason as Error).message }))
      setBudget(b.status === 'fulfilled' ? { value: b.value, failed: '' } : old => ({ value: old.value, failed: (b.reason as Error).message }))
      setLoading(false)
    })
  }
  useEffect(() => read(false), [])
  const words: Record<UsageRole, string> = { literature: 'Literature model', answer: 'Answer model', reviewer: 'Reviewer model' }
  const order: UsageRole[] = ['literature', 'answer', 'reviewer']
  const number = (n: number) => n.toLocaleString(uiLocale())
  const b = budget.value
  const budgetText = !b ? null
    : b.used_fraction !== null ? t('{p}% of budget', { p: Math.round(b.used_fraction * 100) })
    : b.remaining === null ? null
    : b.unit === 'usd' ? t('${x} left today', { x: b.remaining.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })
    : t(b.remaining === 1 ? '{n} credit left today' : '{n} credits left today', { n: number(b.remaining) })
  const failed = month.failed || budget.failed
  return <>
    <h2>{t('Usage this month')}</h2>
    {failed && <div className="notice warn" role="alert"><Info aria-hidden /><div className="nb"><span>{t('Usage could not be read: {message}', { message: failed })}</span>
      <div className="acts"><button type="button" className="ghost" disabled={loading} onClick={() => read()}>{t('Try again')}</button></div></div></div>}
    <div className="rows set-usage">
      {order.map(role => {
        const row = month.value?.roles.find(r => r.role === role)
        return <div key={role} data-role={role}>
          <b>{t(words[role])}</b>
          <div className="bar" aria-hidden><i style={{ width: `${Math.round((row?.share ?? 0) * 100)}%` }} /></div>
          <p className="tnum">{!row ? t(loading && !month.failed ? 'Checking…' : 'not known') : t(row.calls === 1 ? '{n} call' : '{n} calls', { n: number(row.calls) })}</p>
        </div>
      })}
      <div data-role="openalex">
        <b>{t('OpenAlex today')}</b>
        <div className="bar" aria-hidden style={b && b.used_fraction === null ? { visibility: 'hidden' } : undefined}><i style={{ width: `${Math.round((b?.used_fraction ?? 0) * 100)}%`, background: (b?.used_fraction ?? 0) >= 1 ? 'var(--tone-exclude)' : undefined }} /></div>
        <p className="tnum">{budgetText ?? t(loading && !budget.failed ? 'Checking…' : 'not known')}
          <small>{b?.as_of ? t('Last stored response, {time}', { time: clock(b.as_of) }) : b ? t('No OpenAlex response stored today') : ''}</small></p>
      </div>
    </div>
    {month.value?.since && <p className="foot-note set-usage-note">{t('Model calls counted since {date}. The OpenAlex figure comes from its last response, not a live reading.', { date: new Date(month.value.since).toLocaleDateString(uiLocale(), { day: 'numeric', month: 'long' }) })}</p>}
  </>
}
