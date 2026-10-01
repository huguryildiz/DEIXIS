import type { LineageCurrency, LineageReason, LineageRelation, LineageStaleReason, LineageStepOutcome, LineageNode } from '../api'
import { t, uiLocale } from '../i18n'

export const relationLabels: Record<LineageRelation, string> = {
  extends: 'extends', relaxes_assumption: 'relaxes an assumption', changes_method: 'changes method',
  new_domain_or_condition: 'new domain or condition', corrects_or_contradicts: 'corrects or contradicts', independent_parallel: 'independent parallel work',
}
export const reasonLabels: Record<LineageReason, string> = {
  not_run: 'no recorded decision for this work yet', no_pdf_text: 'this work has no stored PDF text',
  no_candidate: 'no earlier work in this table was found mentioned in its stored text',
  no_relation: 'a recorded decision found no relation for the considered pair',
  insufficient_evidence: 'the considered pair had insufficient evidence for a link',
  rejected: 'a proposal for this work was not accepted', not_sent_budget: 'candidates were not sent within the call or message limits',
  step_failed: 'a model call for this work failed', human_removed: 'a human removed a link for this work',
  cross_relation_only: 'this work has only an independent parallel relation', stale_only: 'this work has only links whose inputs changed',
}
export const rejectionLabels: Record<string, string> = {
  anchor_not_found: 'the quoted text could not be located in the later work', same_work: 'the two versions belong to the same work',
  cycle: 'the proposed link would close a directed cycle', stale_input: 'the inputs changed before the proposal was recorded',
  human_precedence: 'a human decision takes precedence', superseded_by_human: 'a human decision takes precedence',
  endpoint_not_included: 'an end is no longer a live included row',
}
export const staleLabels: Record<LineageStaleReason, string> = {
  evidence_not_current: 'a cited passage is no longer current', scope_changed: "the question's scope changed",
  node_changed: 'a development cell changed', passage_changed: 'a passage changed',
}
export const outcomeLabels: Record<LineageStepOutcome['kind'], string> = {
  failed_pair: 'the model call for this pair failed', unsent_pair: 'not sent: the call budget or message size did not allow it',
  step_failed: "a model call failed for this work's candidates", skipped: 'a chunk was skipped when the run stopped',
}
export const uncheckedLabels: Record<string, string> = {
  passage_text: 'passage text', node_snapshots: 'development cell snapshots', passages: 'passages',
  mention_passages: 'mention passages', fingerprint: 'input fingerprint',
}
export const decisionLabels: Record<string, string> = {
  link: 'link', no_relation: 'no relation', insufficient_evidence: 'insufficient evidence', removed: 'removed', none: 'no decision',
}
export const authorText = (author: 'model' | 'human') => t(author === 'model' ? 'model proposal' : 'human decision')
export const supportText = (support: string) => t(support === 'source_stated' ? 'source stated' : 'analyst inference')
export const edgeLabels = { present: 'present', absent_in_read_list: 'not in the read list', unresolved: 'unresolved', not_read: 'not read' }
export const dateText = (date: string) => new Date(date).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' })
export const workText = (node: LineageNode | undefined) => node ? [node.source_key || node.title, node.year].filter(v => v != null).join(' · ') : t('Source record unavailable')
export function currencyText(item: LineageCurrency) {
  const checked = item.current === true ? t('the inputs that were checked are unchanged since')
    : item.current === false ? item.stale_reasons.map(r => t(staleLabels[r])).join('; ') : ''
  const unchecked = item.unchecked.length ? t('not checked: {names}', { names: item.unchecked.map(n => t(uncheckedLabels[n] ?? n)).join(', ') })
    : item.current === null ? t('inputs not checked') : ''
  return [checked, unchecked].filter(Boolean).join('; ')
}
