import type { ModelRole, Run } from '../lib/api'

// The Settings role whose model runs a step task (api/usage_routes.role_of, domain/rules.LITERATURE_TASKS).
const LITERATURE_TASKS = new Set(['question_translation', 'vocabulary_labels', 'criterion_proposal', 'search_query', 'abstract_screening', 'fulltext_adjudication'])
export const roleOfTask = (task: string): ModelRole => LITERATURE_TASKS.has(task) ? 'literature' : task === 'answer_review' ? 'reviewer' : 'answer'
// The role of the model step the run stopped at: its last model step that did not succeed.
export function stoppedRole(run: Run): ModelRole {
  const step = [...(run.steps ?? [])].reverse().find(s => s.kind.startsWith('model:') && s.status !== 'succeeded')
  return step ? roleOfTask(step.kind.slice('model:'.length)) : run.kind === 'discovery' ? 'literature' : 'answer'
}
// Pause reasons of a model that did not answer or answered as another model (flow._model_step).
export const MODEL_DOWN = new Set(['model_call_failed', 'model_connection_not_ready', 'model_connection_unavailable', 'model_mismatch'])
// A stop for a model that did not answer: at the top, or inside the question's translation, which stops the run as
// `key_terms_needed` with the step's own reason.
export function modelDownPause(run: Run): boolean {
  if (MODEL_DOWN.has(run.pause_reason ?? '')) return true
  const translation = run.pause_reason === 'key_terms_needed' && run.error && typeof run.error === 'object'
    ? (run.error as { translation?: { reason?: unknown } }).translation : undefined
  return typeof translation?.reason === 'string' && MODEL_DOWN.has(translation.reason)
}
