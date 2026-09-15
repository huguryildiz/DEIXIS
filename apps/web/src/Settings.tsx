import { useEffect, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { api, type ModelRole, type RoleModelSetting } from './api'
import { connectionModels, defaultEffort, ModelPicker, modelKey, modelRoles, notReadyReasons, type ConnectionModel } from './Home'
import { ConnectionsTab } from './Connections'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'

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

  return <section className="collection legacy-connections settings-page">
    <div className="section-label">{t('SETTINGS')}</div>
    <h1>{t('Settings')}</h1>
    <p>{t('Defaults apply to new researches. Each research keeps the models it was created with, and you can change them for one research from the composer.')}</p>
    {error && <div className="legacy-boundary">{error}</div>}

    <div className="settings-tabs" role="tablist" aria-label={t('Settings sections')}>
      <button type="button" role="tab" id="tab-defaults" aria-selected={tab === 'defaults'} aria-controls="panel-defaults" className={tab === 'defaults' ? 'is-active' : ''} onClick={() => onTab('defaults')}>{t('Default models')}</button>
      <button type="button" role="tab" id="tab-connections" aria-selected={tab === 'connections'} aria-controls="panel-connections" className={tab === 'connections' ? 'is-active' : ''} onClick={() => onTab('connections')}>{t('Connections')}</button>
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
    {tab === 'connections' && <div id="panel-connections" role="tabpanel" aria-labelledby="tab-connections"><ConnectionsTab dark={dark} /></div>}
  </section>
}
