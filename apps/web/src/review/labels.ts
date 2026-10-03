import { t } from '../i18n'
import { kindLabels } from '../candidate/labels'
import type { ReviewDetail, ReviewResolvedTarget, ReviewTargetRef } from '../api'

export const reviewFindingLabels = { unsupported: 'Not supported by the cited text', partially_supported: 'Partly supported by the cited text', overstated: 'Overstated', missing_context: 'Missing context', inconsistent: 'Inconsistent', assumption_unstated: 'Unstated assumption', other: 'Other' }
export const reviewFocusLabels = { source_support: 'Source support', assumptions_and_consistency: 'Assumptions and consistency' }
export const reviewDecisionLabels = { accepted: 'Accepted', dismissed: 'Dismissed', deferred: 'Deferred' }
export const reviewStaleLabels: Record<string, string> = {
  newer_candidate_version: 'a newer candidate version exists', newer_kill_search: 'a newer search exists', kill_search_changed: 'the reviewed search changed', owner_status_changed: 'the owner status changed',
  newer_answer: 'a newer answer exists', scope_revised: 'the question was revised', sources_added: 'sources added', sources_removed: 'sources removed', selection_changed: 'source selection changed', newer_report_version: 'a newer report version exists', report_version_changed: 'report version changed', claim_edited: 'claim edited', claim_removed: 'claim removed', cell_changed: 'cell changed', rows_added: 'rows added', rows_removed: 'rows removed', column_revised: 'column revised', passage_changed: 'passage changed', asset_changed: 'file changed', extraction_changed: 'extraction changed', evidence_missing: 'evidence missing', pdf_replaced: 'PDF replaced', pdf_removed: 'PDF removed', text_superseded: 'text superseded',
}
export const reviewNotReviewedLabels: Record<string, string> = {
  source_too_large: 'source exceeds the request size limit', candidate_too_large: 'candidate exceeds the request size limit',
  claim_too_large: 'claim exceeds the request size limit', too_many_passages: 'too many passages', cell_value_too_large: 'cell value exceeds the input size limit', claim_text_too_long: 'claim text is too long', invalid_model_output: 'model output could not be read', message_too_large: 'request exceeds the size limit', repair_message_too_large: 'repair request exceeds the size limit', deadline_passed: 'review deadline passed',
}
export const reviewContextLabels: Record<string, string> = { passage_missing: 'Passage missing', only_abstract: 'Abstract only', not_enough_context: 'Not enough context', outside_provided_scope: 'Outside the supplied scope' }
export const reviewBoundFields: Record<string, string> = { quote: 'quote', candidate_statement: 'candidate statement', elements: 'elements', conditions: 'conditions', critical_assumption: 'critical assumption', nearest_simple_explanation: 'nearest simple explanation', matrix: 'matrix rows', quotes: 'quotes', whole_claim_quotes: 'whole-claim quotes', reasons: 'reasons', reason: 'reason', note: 'note', element_refs: 'element references', claims: 'claims', cells: 'cells', columns: 'columns', citations: 'citations', sources: 'sources', sections: 'sections', evidence: 'evidence items', text: 'text', value_text: 'cell value text', title: 'title', name: 'name', instruction: 'instruction', owner_note: 'owner note', claim_refs: 'claim references', section_refs: 'section references', passage_ids: 'passage identifiers', source_ids: 'source identifiers', cell_ids: 'cell identifiers', authors: 'authors', body_refs: 'body references', evidence_passage_ids: 'evidence passage identifiers', options: 'options', option_ids: 'option identifiers', label: 'label', doi: 'DOI', version_label: 'version label', steering: 'steering text', question: 'question', rationale: 'rationale', uncertainty: 'uncertainty', suggested_fix: 'suggested fix', possible_impact: 'possible impact' }
export function notReviewedText(code: string) {
  if (reviewNotReviewedLabels[code]) return t(reviewNotReviewedLabels[code])
  const match = /^(too_many)_(.+)$|^(.+)_too_long$/.exec(code)
  const field = match?.[2] ?? match?.[3]
  return field && reviewBoundFields[field] ? t(match?.[1] ? 'Too many {field}' : '{field} is too long', { field: t(reviewBoundFields[field]) }) : code
}
export function claimLabel(review: ReviewDetail, ref: string | null, sectionLabel: (ref: string) => string) {
  const claim = review.snapshot.claims.find(c => c.claim_ref === ref)
  return claim ? [claim.claim_ref, claim.section_ref && sectionLabel(claim.section_ref)].filter(Boolean).join(' · ') : t('an item no longer in the review copy')
}
export function targetLabel(review: ReviewDetail, ref: ReviewTargetRef, sectionLabel: (ref: string) => string) {
  if (ref.kind === 'candidate_element') {
    const element = review.snapshot.elements?.find(e => e.element_ref === ref.ref)
    return element ? t('Element {ref} · {kind}', { ref: element.element_ref, kind: t(kindLabels[element.kind] ?? element.kind) }) : t('an item no longer in the review copy')
  }
  if (ref.kind === 'candidate_source') return review.snapshot.sources.find(s => s.source_id === ref.ref)?.title ?? t('an item no longer in the review copy')
  if (ref.kind === 'whole') return t('several targets')
  if (ref.kind === 'claim') return claimLabel(review, ref.ref, sectionLabel)
  if (ref.kind === 'section') return ref.ref ? sectionLabel(ref.ref) : t('an item no longer in the review copy')
  const cell = review.snapshot.cells.find(c => c.cell_id === ref.ref)
  return cell ? `${cell.column_name} · ${review.snapshot.sources.find(s => s.source_id === cell.source_version_id)?.title ?? t('an item no longer in the review copy')}` : t('an item no longer in the review copy')
}
export function resolvedTargetHeading(review: ReviewDetail, finding: ReviewResolvedTarget, sectionLabel: (ref: string) => string) {
  if (finding.target_ref.kind !== 'whole') return targetLabel(review, finding.target_ref, sectionLabel)
  return t(review.snapshot.target_kind === 'candidate' ? 'The candidate as sent in group {i} of {n}' : 'Claims sent in group {i} of {n}', { i: finding.group_index, n: finding.group_count })
}
export function resolvedGroupClaims(review: ReviewDetail, finding: ReviewResolvedTarget, sectionLabel: (ref: string) => string) {
  if (finding.target_ref.kind !== 'whole') return ''
  const group = review.groups.find(g => g.group_index === finding.group_index)
  if (review.snapshot.target_kind === 'candidate') return group?.source_ids?.map(id => targetLabel(review, { kind: 'candidate_source', ref: id }, sectionLabel)).join(', ') ?? ''
  return group?.claim_refs.map(ref => claimLabel(review, ref, sectionLabel)).join(', ') ?? ''
}
export function resolvedTargetLabel(review: ReviewDetail, finding: ReviewResolvedTarget, sectionLabel: (ref: string) => string) {
  return [resolvedTargetHeading(review, finding, sectionLabel), resolvedGroupClaims(review, finding, sectionLabel)].filter(Boolean).join(' · ')
}
export function staleLabel(review: ReviewDetail, reason: ReviewDetail['stale_reasons'][number], sectionLabel: (ref: string) => string, sourceName: (id: string) => string) {
  const missing = t('an item no longer in the review copy')
  let items: string[] = []
  if (reason.code === 'newer_candidate_version') items = [reason.version != null ? t('Version {n}', { n: reason.version }) : missing]
  else if (reason.code === 'newer_kill_search') items = [reason.kill_search_id && reason.kill_search_id === review.snapshot.kill_search_id ? t('Reviewed search') : missing]
  else if (reason.code === 'kill_search_changed') items = [t('Reviewed search')]
  else if (reason.code === 'owner_status_changed') items = [t('Owner status')]
  else if (review.snapshot.target_kind === 'candidate' && reason.targets) items = reason.targets.map(ref => targetLabel(review, ref, sectionLabel))
  else if (reason.claim_ref) items = [claimLabel(review, reason.claim_ref, sectionLabel)]
  else if (reason.cell_id) {
    const cell = review.snapshot.cells.find(c => c.cell_id === reason.cell_id)
    items = [cell ? `${cell.column_name} · ${sourceName(cell.source_version_id)}` : missing]
  } else if (reason.column_id) items = [review.snapshot.columns.find(c => c.column_id === reason.column_id)?.name ?? missing]
  else if (reason.source_version_ids) items = reason.source_version_ids.map(id => review.snapshot.sources.some(s => s.source_id === id) ? sourceName(id) : missing)
  else if (reason.target_ref?.kind === 'whole') items = [t('several targets')]
  else if (reason.targets) items = reason.targets.map(ref => targetLabel(review, ref, sectionLabel))
  return [t(reviewStaleLabels[reason.code] ?? reason.code), ...items].join(' · ')
}
