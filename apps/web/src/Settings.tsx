import { useEffect, useState } from 'react'
import { api, type ModelOption, type ModelRole, type RoleModelSetting } from './api'
import { defaultEffort, ModelPicker, modelRoles } from './Home'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'

const NO_DEFAULT = '__none'

export function SettingsPage() {
  const toast = useToast()
  const [models, setModels] = useState<ModelOption[] | null>(null)
  const [codexReason, setCodexReason] = useState('')
  const [defaults, setDefaults] = useState<Record<ModelRole, RoleModelSetting> | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.connections().then(result => { setModels(result.models.codex?.models ?? []); setCodexReason(result.models.codex?.reason ?? '') })
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
    <h2>{t('Default models')}</h2>
    {!models || !defaults
      ? <p className="legacy-mini-note">{t('Checking…')}</p>
      : !models.length
        ? <p className="legacy-mini-note">{t('Codex is not ready, so no model can be chosen: {reason}', { reason: codexReason })}</p>
        : <div className="settings-roles">{(Object.keys(modelRoles) as ModelRole[]).map(role => {
            const info = modelRoles[role]
            const current = defaults[role]
            const none = role === 'reviewer'
              ? { value: NO_DEFAULT, title: t('No default reviewer'), detail: t('Answers are reviewed only in researches that set their own reviewer') }
              : { value: NO_DEFAULT, title: t('No default'), detail: t('New researches start with the model Codex marks as its default') }
            return <div className="settings-role" key={role}>
              <div className="settings-role-text"><strong>{t(info.label)}</strong><small>{t(info.hint)}</small></div>
              <div className="composer-options">
                <ModelPicker role={t(info.label)} icon={info.icon} hint={t(info.hint)} models={models} value={current.model ?? NO_DEFAULT}
                  onChange={v => save(role, { model_connection: 'codex', model: v === NO_DEFAULT ? null : v, reasoning_effort: v === NO_DEFAULT ? null : defaultEffort(models, v) })}
                  effort={current.reasoning_effort} onEffort={e => save(role, { ...current, reasoning_effort: e })} choices={[none]} />
              </div>
            </div>
          })}</div>}
  </section>
}
