import { downloadName } from '../downloadName'
import { type Answer, type Evidence, type Limitation, type Source, type Verdict } from '../api'
import { locatorText, pageLocator, verdictLabels } from '../labels'
import { formatReferenceText, type CitationStyle } from '../citations'
import { OCR_LABEL } from '../ocr'
import { t } from '../i18n'

// The report of a valid answer as parts and as a Markdown file. The report panel (Copy, Download) and the topbar Export
// menu (UI parity S8) write the same file. Split from AnswerBlock.tsx.

// A claim review's tone (mockup `.badge-s`): supported green, partly supported amber, not supported red, cannot assess plain.
export const verdictTones: Record<Verdict, string> = { supported: 'ok', partially_supported: 'part', not_supported: 'bad', cannot_assess: 'plain' }

function reportFilename(title: string, version: number) {
  return downloadName(title, [`V${version}`], 'md', 'Report')
}

function pdfSuggestion(answer: Answer, sources: Source[]): { notes: Limitation[]; sources: Source[] } | null {
  if (answer.status !== 'structurally_valid' || answer.applicability === 'stale_scope') return null
  const lacking = (ids: string[]) => [...new Set(ids)]
    .map(id => sources.find(s => s.source_version_id === id && s.origin === 'provider' && !s.access.assets.length))
    .filter((s): s is Source => Boolean(s))
  const notes = answer.limitations.filter(l => l.kind === 'access' && lacking(l.source_ids).length > 0)
  const listed = lacking(notes.length ? notes.flatMap(l => l.source_ids) : answer.claims.flatMap(c => c.evidence.map(e => e.source_version_id)))
  return listed.length ? { notes, sources: listed } : null
}

// The report's numbered references, its sections and the limits shown under it. The Markdown file (report sheet and
// the topbar Export menu, S8) and the rendered report read the same parts.
// `style`: IEEE cites by number (the reference's [n]); the other styles by the source's key when it has one.
export function reportParts(answer: Answer, sources: Source[], style?: CitationStyle) {
  const refs = new Map<string, { n: number; e: Answer['claims'][number]['evidence'][number] }>()
  answer.claims.forEach(c => c.evidence.forEach(e => { if (!refs.has(e.passage_id)) refs.set(e.passage_id, { n: refs.size + 1, e }) }))
  // A citation names its source's key (D59); a claim citing two passages of one source adds each passage's place.
  const citeLabel = (claim: Answer['claims'][number], e: Evidence) => {
    if (!e.source_key || style === 'ieee') return `${refs.get(e.passage_id)?.n}`
    const repeated = claim.evidence.filter(x => x.source_version_id === e.source_version_id).length > 1
    return repeated ? `${e.source_key}, ${e.kind === 'abstract' ? t('abstract') : e.physical_page ? pageLocator(e.physical_page, e.rendition) : t('section')}` : e.source_key
  }
  // Consecutive claims with the same heading form one report section; answers saved before sections have no heading.
  const sections: { heading: string | null; claims: Answer['claims'] }[] = []
  answer.claims.forEach(c => { const last = sections[sections.length - 1]; if (last && last.heading === c.section) last.claims.push(c); else sections.push({ heading: c.section, claims: [c] }) })
  // An access limitation shown with the PDF suggestions is not repeated under Limits.
  const suggestion = pdfSuggestion(answer, sources)
  const limits = answer.limitations.filter(l => !suggestion?.notes.includes(l))
  return { refs, citeLabel, sections, suggestion, limits }
}

export function reportMarkdown(answer: Answer, sources: Source[], title: string, version: number, style: CitationStyle) {
  const { refs, citeLabel, sections, limits } = reportParts(answer, sources, style)
  const lines = [`# ${title}`, '', `${t('Report')} · V${version}`, '']
  if (answer.applicability === 'stale_scope') lines.push(`> ${t('This answer was produced for revision {n} of the question and is not applied to the current revision.', { n: answer.scope_revision })}`, '')
  if (answer.applicability === 'stale_selection') lines.push(`> ${t('Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added.')}`, '')
  if (answer.capability_notice) lines.push(`> ${answer.capability_notice}`, '')
  sections.forEach(({ heading, claims }) => {
    if (heading) lines.push(`## ${heading}`, '')
    claims.forEach(claim => {
      const citations = claim.evidence.map(e => `[${citeLabel(claim, e)}]`).join('')
      const inference = claim.support_type === 'analyst_inference' ? ` _(${t('interpretation')})_` : ''
      const review = claim.review ? ` _${t('Reviewer: {reason}', { reason: `${t(verdictLabels[claim.review.verdict])} — ${claim.review.reason}` })}_` : ''
      lines.push(`${claim.text}${citations ? ` ${citations}` : ''}${inference}${review}`, '')
    })
  })
  if (!answer.claims.length) lines.push(t('No claim could be linked to the passages given to the model.'), '')
  if (answer.unanswered_aspects.length) lines.push(`## ${t('Not answered by the inspected passages')}`, '', ...answer.unanswered_aspects.map(item => `- ${item}`), '')
  if (limits.length) lines.push(`## ${t('Limits')}`, '', ...limits.map(limit => `- **${t(limit.kind.replace('_', ' '))}:** ${limit.text}`), '')
  if (refs.size) {
    lines.push(`## ${t('Cited passages')}`, '')
    refs.forEach(({ n, e }) => {
      const source = sources.find(s => s.source_version_id === e.source_version_id)
      lines.push(`[${style === 'ieee' ? n : e.source_key ?? n}] ${source ? formatReferenceText(style, source) : e.title} — ${locatorText(e)}${e.text_source === 'ocr' ? ` (${t(OCR_LABEL)})` : ''}${e.text_source === 'latex_source' ? ` (${t('arXiv source')})` : ''}${e.text_source === 'equation_ocr' ? ` (${t('equations read by Mathpix')})` : ''}`)
    })
    lines.push('')
  }
  lines.push(`---`, '', t('Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked.'))
  return `${lines.join('\n').trim()}\n`
}

export function downloadReportMarkdown(answer: Answer, sources: Source[], title: string, version: number, style: CitationStyle) {
  const url = URL.createObjectURL(new Blob([reportMarkdown(answer, sources, title, version, style)], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = reportFilename(title, version)
  link.click()
  URL.revokeObjectURL(url)
}
