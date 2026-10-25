import type { ModelOption } from './api'

// Gemini CLI has no user-facing effort control. Keep its internal API thinking configuration out of the UI and requests.
type SelectableModel = ModelOption & { connection?: string }
export const exposesEffortControl = (model: SelectableModel | undefined) => model?.connection !== 'gemini'

// Each model with a user-facing effort control starts from the model's declared default.
export const defaultEffort = (models: SelectableModel[], id: string) => {
  const m = models.find(x => x.id === id)
  if (!exposesEffortControl(m)) return null
  return m?.default_reasoning_effort ?? null
}
export const listedEffort = (models: SelectableModel[], id: string, effort: string | null) => {
  const model = models.find(m => m.id === id)
  return exposesEffortControl(model) && model?.reasoning_efforts?.some(e => e.id === effort) ? effort : null
}
