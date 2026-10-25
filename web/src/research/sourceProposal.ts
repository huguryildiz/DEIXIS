import { type ReadCoverage, type Source } from '../lib/api'
import { hasQueueReason, queueReasonText, waitingReasonText } from '../lib/labels'
import { t } from '../lib/i18n'

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
  abstract_not_proposed: 'No valid model proposal was recorded for its abstract.',
  survey_title_word: 'The title names a survey or review, so it went to the seed pool instead of screening.',
}
// The basis of an abstract-stage decision, from what its reason code read: the title alone, the record's metadata, the
// title and abstract by a code rule, or two model reads of them. A code with no reading (no abstract, not read, no valid
// proposal) has no basis line.
const ABSTRACT_BASIS: Record<string, string> = {
  blocks_in_title: 'basis: title · code rule',
  survey_title_word: 'basis: title · code rule',
  notice_record: 'basis: record metadata · code rule',
  artifact_of_paper: 'basis: record metadata · code rule',
  both_blocks_missing: 'basis: title and abstract · code rule',
  runs_agree_candidate: 'basis: title and abstract · two reads',
  runs_agree_out_of_scope: 'basis: title and abstract · two reads',
  runs_agree_unresolved: 'basis: title and abstract · two reads',
  runs_disagree_kept_as_candidate: 'basis: title and abstract · two reads',
  quote_not_found_kept_as_candidate: 'basis: title and abstract · two reads',
}
// "All text parts" is every extracted text part, never the whole PDF: a page without text has no part (audit item 3).
function readingBasis(c: ReadCoverage | null): string {
  if (!c) return t('basis: full text (selected pages) · two reads')
  if (c.all_parts_shown) return t(c.parts_total === 1 ? 'basis: full text · its one text part read · two reads' : 'basis: full text · all {n} text parts read · two reads', { n: c.parts_total })
  return t('basis: full text · {k} of {n} text parts read, from {p} of {q} pages · two reads', { k: c.parts_shown, n: c.parts_total, p: c.pages_shown, q: c.pdf_pages ?? c.pages_with_text })
}
const NOT_READ = new Set(['no_abstract', 'abstract_not_found', 'abstract_not_read', 'abstract_not_proposed'])
export function proposalOf(source: Source): Proposal | null {
  const sc = source.screening
  if (sc?.stage === 'fulltext') {
    const code = sc.reason_code ?? ''
    // Not read in full: no readable PDF yet, text in hand that waits to be read, or a file not yet confirmed as this
    // work's. None of these is a reading, so none has a basis line.
    if (sc.next_step === 'waiting_for_pdf') return { tone: 'none', word: t('not read in full'), reason: waitingReasonText(code), basis: '' }
    if (sc.next_step === 'reading_queue') return { tone: 'none', word: t('not read in full'), reason: t('The full text is in hand and waits to be read.'), basis: '' }
    if (code === 'pdf_identity_unconfirmed') return { tone: 'none', word: t('not read in full'), reason: queueReasonText(code), basis: '' }
    // A reading happened: two model runs read the selected pages (the agreement or the rule applied to it decides). The
    // decision's recorded coverage says how much of the extracted text they were shown; older decisions have none.
    const basis = readingBasis(sc.read_coverage)
    if (sc.outcome === 'include') return { tone: 'include', word: t('include'), reason: t('Both full-text reads found every part of the criterion.'), basis }
    if (sc.outcome === 'criterion_not_met') return { tone: 'exclude', word: t('exclude'), reason: t('The parts of the criterion were not found in the passages read.'), basis }
    return { tone: 'uncertain', word: t('uncertain'), reason: hasQueueReason(code) ? queueReasonText(code) : t('Left open at the full-text stage.'), basis }
  }
  if (sc?.stage === 'abstract') {
    const code = sc.reason_code ?? ''
    const reason = ABSTRACT_REASONS[code]
    const basis = ABSTRACT_BASIS[code] ? t(ABSTRACT_BASIS[code]) : ''
    if (sc.outcome === 'candidate') return { tone: 'passed', word: t('passed abstract'), reason: t(reason ?? 'Kept for the full text.'), basis }
    if (sc.outcome === 'out_of_scope') return { tone: 'exclude', word: t('exclude'), reason: t(reason ?? 'Out of scope at the abstract stage.'), basis }
    if (NOT_READ.has(code)) return { tone: 'none', word: t('not screened'), reason: t(reason), basis }
    return { tone: 'uncertain', word: t('uncertain'), reason: t(reason ?? 'Left open at the abstract stage.'), basis }
  }
  // Decisions made under an earlier question or criterion are left out by the backend; none stands for the current one.
  if (sc?.stale) return { tone: 'none', word: t('not screened'), reason: t('Screened under an earlier question or criterion; not screened for the current one yet.'), basis: '' }
  const s = source.selection
  if (s.proposal) return { tone: s.proposal === 'include' ? 'include' : s.proposal === 'exclude' ? 'exclude' : 'uncertain', word: t(s.proposal), reason: s.proposal_reason ?? '', basis: s.proposal_basis ? t('basis: {basis}', { basis: t(s.proposal_basis.replaceAll('_', ' ')) }) : '' }
  return null
}
