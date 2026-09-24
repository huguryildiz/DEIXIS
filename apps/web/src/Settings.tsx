import { useEffect, useState } from 'react'
import { Landmark, SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type ModelRole, type RoleModelSetting } from './api'
import { connectionModels, defaultEffort, ModelPicker, modelKey, modelRoles, notReadyReasons, type ConnectionModel } from './Home'
import { ConnectionsTab } from './Connections'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'
import { Notice } from './Notice'

const NO_DEFAULT = '__none'

export function SettingsPage({ dark, tab, onTab }: { dark: boolean; tab: 'defaults' | 'connections'; onTab: (tab: 'defaults' | 'connections') => void }) {
  const toast = useToast()
  const [models, setModels] = useState<ConnectionModel[] | null>(null)
  const [notReady, setNotReady] = useState('')
  const [defaults, setDefaults] = useState<Record<ModelRole, RoleModelSetting> | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.connections().then(result => { setModels(connectionModels(result)); setNotReady(notReadyReasons(result)) })
      .catch((e: Error) => setError(e.message))
    api.settings().then(setDefaults).catch((e: Error) => setError(e.message))
  }, [])

  function save(role: ModelRole, next: RoleModelSetting) {
    const label = t(modelRoles[role].label).toLocaleLowerCase(uiLocale())
    api.saveModelDefault(role, next).then(saved => {
      setDefaults(old => old && { ...old, [role]: saved[role] ?? next })
      toast('success', next.model ? t('Default {role} model: {model}', { role: label, model: next.model }) : t('No default {role} model', { role: label }))
    }).catch((e: Error) => toast('error', t('Could not save the default: {message}', { message: e.message })))
  }

  return <section className="collection legacy-connections">
    <div className="section-label">{t('Settings')}</div>
    <h1>{t('Settings')}</h1>
    <p>{t('Defaults apply to new researches. Each research keeps the models it was created with, and you can change them for one research from the composer.')}</p>
    {error && <Notice tone="error">{error}</Notice>}

    <div className="tab-strip settings-tabs" role="tablist" aria-label={t('Settings sections')}>
      <button type="button" role="tab" id="tab-defaults" aria-selected={tab === 'defaults'} aria-controls="panel-defaults" onClick={() => onTab('defaults')}>{t('Default models')}</button>
      <button type="button" role="tab" id="tab-connections" aria-selected={tab === 'connections'} aria-controls="panel-connections" onClick={() => onTab('connections')}>{t('Connections')}</button>
    </div>

    {tab === 'defaults' && <div id="panel-defaults" role="tabpanel" aria-labelledby="tab-defaults">
      <h2 className="with-icon"><SlidersHorizontal size={20} aria-hidden />{t('Default models')}</h2>
      {!models || !defaults
        ? <p className="legacy-mini-note">{t('Checking…')}</p>
        : !models.length
          ? <p className="legacy-mini-note">{t('No model connection is ready, so no model can be chosen: {reason}', { reason: notReady })}</p>
          : <div className="settings-roles">{(Object.keys(modelRoles) as ModelRole[]).map(role => {
              const info = modelRoles[role]
              const RoleIcon = info.icon
              const current = defaults[role]
              const none = role === 'reviewer'
                ? { value: NO_DEFAULT, title: t('No default reviewer'), detail: t('Answers are reviewed only in researches that set their own reviewer') }
                : { value: NO_DEFAULT, title: t('No default'), detail: t('New researches start with the model Codex marks as its default') }
              return <div className="settings-role" key={role}>
                <div className="settings-role-text"><strong className="with-icon"><RoleIcon size={16} aria-hidden />{t(info.label)}</strong><small>{t(info.hint)}</small></div>
                <div className="composer-options">
                  <ModelPicker role={t(info.label)} icon={info.icon} hint={t(info.hint)} models={models}
                    value={current.model ? modelKey(current.model_connection, current.model) : NO_DEFAULT}
                    onChange={v => {
                      const m = models.find(x => x.id === v)
                      save(role, m ? { model_connection: m.connection, model: m.model, reasoning_effort: defaultEffort(models, v) }
                        : { model_connection: current.model_connection, model: null, reasoning_effort: null })
                    }}
                    effort={current.reasoning_effort} onEffort={e => save(role, { ...current, reasoning_effort: e })} choices={[none]} />
                </div>
              </div>
            })}</div>}
    </div>}
    {tab === 'connections' && <div id="panel-connections" role="tabpanel" aria-labelledby="tab-connections"><InstitutionProxy /><ConnectionsTab dark={dark} /></div>}
  </section>
}

// The institution's proxy address (slice 18a): the links of works waiting for a PDF open through it in the browser, where
// the institution's own login happens. DEIXIS never sends a request through it and stores no password.
function InstitutionProxy() {
  const toast = useToast()
  const [saved, setSaved] = useState<string | null | undefined>(undefined)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.institutionProxy().then(result => { setSaved(result.address); setDraft(result.address ?? '') }).catch((e: Error) => setError(e.message))
  }, [])
  const save = (address: string) => {
    setBusy(true)
    api.saveInstitutionProxy(address).then(result => {
      setSaved(result.address); setDraft(result.address ?? ''); setError('')
      toast('success', t(result.address ? 'Proxy address saved. Links of works waiting for a PDF open through it.' : 'Proxy address removed. Links open directly.'))
    }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  return <section className="connections-group proxy-setting" aria-labelledby="proxy-title">
    <h2 id="proxy-title" className="with-icon"><Landmark size={20} aria-hidden />{t('Institution proxy')}</h2>
    <p className="legacy-mini-note">{t('The links of works waiting for your PDF open through this address in your browser, where your institution asks you to sign in. DEIXIS sends nothing through it, downloads nothing from it and never stores a password. Whether your institution grants access is not checked.')}</p>
    <form className="proxy-form" onSubmit={e => { e.preventDefault(); save(draft) }}>
      <label htmlFor="proxy-address">{t('Proxy address')}</label>
      <input id="proxy-address" type="url" inputMode="url" spellCheck={false} autoComplete="off" value={draft} disabled={saved === undefined || busy}
        placeholder="https://login.proxy.example.edu/login?url=" aria-describedby="proxy-help" onChange={e => { setDraft(e.target.value); setError('') }} />
      <small id="proxy-help">{t('A prefix the link is appended to, or an address with {url} where the link goes. https only; no user name or password.')}</small>
      <span className="proxy-actions">
        <Button type="submit" size="sm" disabled={busy || saved === undefined || draft.trim() === (saved ?? '')}>{t('Save')}</Button>
        {saved && <button type="button" className="pdf-ready-link" disabled={busy} onClick={() => save('')}>{t('Remove')}</button>}
      </span>
    </form>
    {error && <Notice tone="error">{error}</Notice>}
  </section>
}
