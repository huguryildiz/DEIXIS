import { t, uiLocale } from '../i18n'
import type { CandidateComputed } from '../api'

export const statusLabels: Record<string, string> = { not_run: 'Not searched', undecided: 'Undecided', narrowed: 'Narrowed', closed: 'Closed', open: 'Open' }
export const kindLabels: Record<string, string> = { stated_limitation: 'stated limitation', conflicting_evidence: 'conflicting evidence', corpus_absence: 'absent from the corpus read', mechanism: 'mechanism', condition: 'condition', outcome: 'outcome', parameter: 'parameter' }
export const relationLabels: Record<string, string> = { explicit_support: 'stated in the text', reasoned_inference: 'inferred from the text', partial_match: 'partly matched', no_match_in_supplied_text: 'no match in the text shown', uncertain: 'uncertain' }
export const alignmentLabels: Record<string, string> = { aligned: 'same conditions', different_conditions: 'different conditions', unclear: 'conditions unclear' }
export const depthLabels: Record<string, string> = { abstract: 'abstract', stored_passages: 'stored passages', metadata_only: 'metadata only' }
export const assessmentLabels: Record<string, string> = {
  assessed: 'assessed', insufficient_access: 'assessment could not be completed: usable text was unavailable (no abstract or stored text, or the frozen text could no longer be read)',
  not_assessed_budget: 'assessment did not complete', pending: 'no published assessment',
}
export const outcomeLabels: Record<string, string> = {
  ...assessmentLabels, invalid_output: 'the model output was invalid', message_too_large: 'the message was too large',
  not_reached_budget: 'assessment was not reached within the run budget', running: 'running', paused: 'paused', completed: 'completed', failed: 'failed', stopped: 'stopped',
  succeeded: 'succeeded', outcome_unknown: 'outcome unknown', related: 'related', unrelated: 'unrelated', uncertain: 'uncertain',
  pending: 'no published assessment', queued: 'queued', pause_requested: 'pause requested', cancelled: 'cancelled', skipped: 'skipped',
}
export const stepStateLabels: Record<string, string> = { ...outcomeLabels, pending: 'not started' }
export const reasonLabels: Record<string, string> = {
  not_searched: 'No search has been recorded for this version.',
  whole_claim_stated: 'One assessed work states the whole claim under the same conditions; its quoted text is shown below. Whether the text supports the claim has not been checked.',
  partial_overlap: 'Partial overlap was recorded for the assessed works. This assessment did not establish that the whole claim is stated together under the same conditions.',
  no_match_in_assessed_subset: 'No match was found among the {assessed} works that were assessed (of {found} results found; {unread} were not read). This says nothing about works that were not read.',
  search_running: 'The search is running; its assessments are incomplete.', search_paused: 'The search is paused; its assessments are incomplete.',
  search_failed: 'No recorded query succeeded; the search could not settle the claim.', search_incomplete: 'The search stopped early or failed; its assessments are incomplete.',
  query_outcome_unknown: 'A query has an unknown outcome; the recorded results do not settle the claim.',
  insufficient_access: 'A work could not be assessed because usable text was unavailable.', not_assessed_budget: 'A kept work’s assessment did not complete.',
  uncertain_relevance: 'The relevance of an assessed work is uncertain.', uncertain_cell: 'An assessed element has an uncertain relation.',
  unclear_alignment: 'The conditions of an assessed relation are unclear.', unclassified: 'The recorded matrix does not fit a settled status.',
}
export const warningLabels: Record<string, string> = { merge_missing: 'The search results have no recorded merge.' }
export const refusalLabels: Record<string, string> = { candidate_not_decomposed: 'Write or break down the claim before planning a search.', no_searchable_provider: 'No selected provider can search this claim.' }
export const runReasonLabels: Record<string, string> = {
  query_terms_invalid: 'The search terms failed the contract checks.', no_query_compiled: 'No provider query could be built from the stored terms.',
  candidate_unavailable: 'The candidate is no longer available.', candidate_version_changed: 'The candidate version changed before publication.',
  candidate_publication_failed: 'The claim breakdown could not be stored.', candidate_evidence_unlocated: 'The quoted text could not be located in the supplied passages.',
  frozen_passage_unavailable: 'The frozen passage could no longer be read.', no_shown_text: 'No usable text was available for assessment.',
  transport_budget: 'The provider-request ceiling was reached.', skill_package_changed: 'The research method changed after this run was planned.',
  invalid_model_output: 'The model output failed the contract checks.', message_too_large: 'The message was too large.',
  model_call_failed: 'The model call did not complete.', after_send_unknown: 'Whether the request completed is unknown.',
  search_failed: 'The provider search failed.', provider_failed: 'The provider search failed.', provider_timeout: 'The provider did not answer in time.',
  provider_rate_limited: 'The provider rate-limited the request.', provider_auth_required: 'The provider requires authentication.',
  provider_entitlement_missing: 'The provider did not accept the configured access.', provider_parse_error: 'The provider response could not be read.',
  failed: 'The provider search failed.', timeout: 'The provider did not answer in time.', rate_limited: 'The provider rate-limited the request.',
  auth_required: 'The provider requires authentication.', entitlement_missing: 'The provider did not accept the configured access.',
  not_configured: 'The provider is not configured.', parse_error: 'The provider response could not be read.',
  outcome_unknown: 'Whether the request completed is unknown.', budget_exhausted: 'The run’s budget was exhausted.',
}
export const label = (map: Record<string, string>, code: string) => map[code] ? t(map[code]) : code
export const reasonText = (computed: CandidateComputed, code = computed.reason) => reasonLabels[code] ? t(reasonLabels[code], { assessed: computed.facts.assessed, found: computed.facts.found, unread: computed.facts.unread }) : code
export const dateText = (date: string) => new Date(date).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' })
export const errorText = (error: unknown) => error instanceof Error ? error.message : String(error)
