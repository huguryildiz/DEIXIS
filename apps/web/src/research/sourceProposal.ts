import { type Source } from '../api'
import { queueReasonText } from '../labels'
import { t } from '../i18n'

// The "Model proposal" column (mockup P9): what code and the model runs decided about the work, from the view's
// `screening` (current, not stale decisions; a person's own decision is the next column). Older researches carry the
// selection's stored proposal instead. Every word names a stored decision; nothing here is a relevance judgment.
type Proposal = { tone: 'include' | 'passed' | 'uncertain' | 'exclude' | 'none'; word: string; reason: string; basis: string }
const ABSTRACT_REASONS: Record<string, string> = {
  runs_agree_candidate: 'Both reads found that the abstract may meet the criterion.',
  runs_disagree_kept_as_candidate: 'The two reads disagreed, so it was kept for the full text.',
  quote_not_found_kept_as_candidate: 'A quoted phrase was not found in the abstract, so it was kept for the full text.',
  blocks_in_title: 'The title names the question’s terms.',
  runs_agree_out_of_scope: 'Both reads found the abstract outside the criterion.',
  both_blocks_missing: 'The title and abstract name none of the question’s terms.',
  notice_record: 'A correction, retraction or withdrawal notice.',
  artifact_of_paper: 'A data or code record of a paper the search also found.',
  runs_agree_unresolved: 'Neither read could tell from the abstract.',
  no_abstract: 'No abstract was found, so the model did not read it.',
  abstract_not_found: 'No abstract was found, so the model did not read it.',
  abstract_not_read: 'Below the read limit of the run; the model was not asked.',
  abstract_not_proposed: 'Below the read limit of the run; the model was not asked.',
}
const NOT_READ = new Set(['no_abstract', 'abstract_not_found', 'abstract_not_read', 'abstract_not_proposed'])
export function proposalOf(source: Source): Proposal | null {
  const sc = source.screening
  if (sc?.stage === 'fulltext') {
    const two = sc.decided_by === 'model_agreement'
    const basis = t(two ? 'basis: full text (selected pages) · two reads' : 'basis: full text · code rule')
    if (sc.outcome === 'include') return { tone: 'include', word: t('include'), reason: t(two ? 'Both full-text reads found every part of the criterion.' : 'Included at the full-text stage.'), basis }
    if (sc.outcome === 'criterion_not_met') return { tone: 'exclude', word: t('exclude'), reason: t('The parts of the criterion were not found in the passages read.'), basis }
    return { tone: 'uncertain', word: t('uncertain'), reason: queueReasonText(sc.reason_code ?? ''), basis }
  }
  if (sc?.stage === 'abstract') {
    const code = sc.reason_code ?? ''
    const reason = ABSTRACT_REASONS[code]
    const basis = NOT_READ.has(code) ? '' : t(sc.decided_by === 'model_agreement' || code === 'runs_disagree_kept_as_candidate' ? 'basis: title and abstract · two reads' : 'basis: title and abstract · code rule')
    if (sc.outcome === 'candidate') return { tone: 'passed', word: t('passed abstract'), reason: t(reason ?? 'Kept for the full text.'), basis }
    if (sc.outcome === 'out_of_scope') return { tone: 'exclude', word: t('exclude'), reason: t(reason ?? 'Out of scope at the abstract stage.'), basis }
    if (NOT_READ.has(code)) return { tone: 'none', word: t('not screened'), reason: t(reason), basis }
    return { tone: 'uncertain', word: t('uncertain'), reason: t(reason ?? 'Left open at the abstract stage.'), basis }
  }
  const s = source.selection
  if (s.proposal) return { tone: s.proposal === 'include' ? 'include' : s.proposal === 'exclude' ? 'exclude' : 'uncertain', word: t(s.proposal), reason: s.proposal_reason ?? '', basis: s.proposal_basis ? t('basis: {basis}', { basis: t(s.proposal_basis.replaceAll('_', ' ')) }) : '' }
  return null
}
