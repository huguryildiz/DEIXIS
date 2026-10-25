import { useEffect, useState } from 'react'
import { api, type ModelOption } from './api'
import { reasoningLabel } from './labels'
import { t } from './i18n'

// Models are named by the display names their connections list. The list is fetched once and shared; until it arrives, or
// for a model no longer listed, the stored model id is shown.
let listed: Promise<ModelOption[]> | null = null
function modelList() {
  listed ??= api.connections().then(c => Object.values(c.models).flatMap(h => h.models ?? [])).catch(() => { listed = null; return [] })
  return listed
}

export type ModelText = (model: string | null, effort?: string | null) => string

export function useModelText(): ModelText {
  const [models, setModels] = useState<ModelOption[]>([])
  useEffect(() => {
    let cancelled = false
    void modelList().then(list => { if (!cancelled) setModels(list) })
    return () => { cancelled = true }
  }, [])
  return (model, effort) => {
    if (!model) return t('no model chosen')
    const option = models.find(m => m.id === model) ?? models.find(m => m.resolved_model === model)
    const name = option?.display_name ?? model
    const eff = effort === undefined ? null : effort || option?.default_reasoning_effort
    return eff ? `${name} · ${reasoningLabel(eff)}` : name
  }
}
