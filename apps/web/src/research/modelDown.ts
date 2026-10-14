import type { ModelRole, Run } from '../api'

// The Settings role whose model runs a step task (api/usage_routes.role_of, domain/rules.LITERATURE_TASKS).
const LITERATURE_TASKS = new Set(['vocabulary_labels', 'criterion_proposal', 'search_query', 'abstract_screening', 'fulltext_adjudication'])
export const roleOfTask = (task: string): ModelRole => LITERATURE_TASKS.has(task) ? 'literature' : task === 'answer_review' ? 'reviewer' : 'answer'
// The role of the model step the run stopped at: its last model step that did not succeed.
export function stoppedRole(run: Run): ModelRole {
  const step = [...(run.steps ?? [])].reverse().find(s => s.kind.startsWith('model:') && s.status !== 'succeeded')
  return step ? roleOfTask(step.kind.slice('model:'.length)) : run.kind === 'discovery' ? 'literature' : 'answer'
}
// Pause reasons of a model that did not answer or answered as another model (flow._model_step).
export const MODEL_DOWN = new Set(['model_call_failed', 'model_connection_not_ready', 'model_connection_unavailable', 'model_mismatch'])
