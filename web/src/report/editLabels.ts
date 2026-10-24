import { t } from '../i18n'

const ruleLabels: Record<string, string> = {
  banned_word: 'banned word', count_number_mismatch: 'count number mismatch',
  limitations_number_restated: 'number restated in limitations', math_not_well_formed: 'malformed math',
}
const skippedLabels: Record<string, string> = {
  count_text_not_checked: 'text count not checked', derived_depth_not_checked: 'derived evidence depth not checked',
  phrase_frames: 'required phrase frames',
}
const reasonLabels: Record<string, string> = {
  human_text: 'edited text: required phrase frames are not checked',
  no_integer_in_text: 'no whole number in the text to compare',
  no_citation_depth: 'no citation to read the evidence depth from',
}
const limits: Record<string, string> = {
  semantic_support: 'whether the cited evidence supports each sentence',
  numbers_written_as_words: 'numbers written as words', passages: 'passages',
}
export const editRuleLabel = (code: string) => t(ruleLabels[code] ?? code.replaceAll('_', ' '))
export const skippedRuleLabel = (code: string) => t(skippedLabels[code] ?? code.replaceAll('_', ' '))
export const skippedReasonLabel = (code: string) => t(reasonLabels[code] ?? code.replaceAll('_', ' '))
export const notCheckedLabel = (code: string) => limits[code] ? t(limits[code]) : code
export const checkCounts = (errors: number, warnings: number) => ({
  errors: t(errors === 1 ? '{n} error' : '{n} errors', { n: errors }),
  warnings: t(warnings === 1 ? '{n} warning' : '{n} warnings', { n: warnings }),
})
export const citationCount = (n: number) => n === 0 ? t('No citations') : t(n === 1 ? '{n} citation' : '{n} citations', { n })
