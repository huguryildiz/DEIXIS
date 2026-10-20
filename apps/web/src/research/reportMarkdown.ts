import { downloadName } from '../downloadName'
import { type Answer, type Evidence, type EvidenceLedger, type LedgerReason, type LedgerWork, type Limitation, type Source, type Verdict } from '../api'
import { equationReaderName, locatorText, pageLocator, verdictLabels } from '../labels'
import { formatReferenceText, inTextCitation, type CitationStyle } from '../citations'
import { OCR_LABEL } from '../ocr'
import { t, uiLocale } from '../i18n'

// The report of a valid answer as parts and as a Markdown file. The report panel (Copy, Download) and the topbar Export
// menu (UI parity S8) write the same file. Split from AnswerBlock.tsx.

// A claim review's tone (mockup `.badge-s`): supported green, partly supported amber, not supported red, cannot assess plain.
export const verdictTones: Record<Verdict, string> = { supported: 'ok', partially_supported: 'part', not_supported: 'bad', cannot_assess: 'plain' }

// The evidence ledger (D80) in words, as the report, the thread and the Markdown file write it (exports/answer.py too).
// Cited counts come from the answer's evidence links; a reason is the model's, checked only for its shape and quote.
const LEDGER_REASONS: Record<LedgerReason, string> = {
  no_answering_content: 'Its given passages do not answer the question',
  off_topic: 'Not about the subject of the question',
  same_finding_as_cited: 'Same finding as a cited work',
  different_conditions: 'Answers part of the question under other conditions',
  claim_limit: 'Left out to stay within the 30-claim limit',
}
const ledgerCount = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
export function ledgerLine(ledger: EvidenceLedger) {
  const line = t('{c} of {m} given works cited · {k} left out with a reason', { c: ledgerCount(ledger.cited.length), m: ledgerCount(ledger.given.length), k: ledgerCount(ledger.excluded.length) })
  return ledger.unaccounted.length ? `${line} · ${t('{u} with no reason recorded', { u: ledgerCount(ledger.unaccounted.length) })}` : line
}
// The works given and not cited, in the ledger's order: those with a reason, then those with none. `reason` is in
// words; `sameAs` is the stored title of the cited work a same-finding entry names.
export type LedgerRow = { work: LedgerWork; passageId: string | null; anchorText: string | null; reason: string; sameAs: string | null; note: string | null }
export function ledgerRows(ledger: EvidenceLedger): LedgerRow[] {
  return [
    ...ledger.excluded.map(e => ({ work: e, passageId: e.passage_id, anchorText: e.anchor_text, note: e.note, reason: t(LEDGER_REASONS[e.reason]),
      sameAs: e.reason === 'same_finding_as_cited' ? e.same_as?.title ?? null : null })),
    ...ledger.unaccounted.map(u => ({ work: u, passageId: u.passage_id, anchorText: null, note: null, sameAs: null, reason: t('No reason was recorded for this work.') })),
  ]
}
// Whether a ledger read from the view has its lists and fields and its counts add up (given splits into disjoint cited,
// excluded and unaccounted works); anything else is not shown, rather than miscounted (exports/answer.py `ledger_ok`).
export function ledgerOk(ledger: unknown): ledger is EvidenceLedger {
  const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
  const work = (v: unknown): v is Record<string, unknown> => record(v) && typeof v.source_version_id === 'string' && (v.title === null || typeof v.title === 'string')
  if (!record(ledger)) return false
  const { given, cited, excluded, unaccounted } = ledger
  if (!Array.isArray(given) || !Array.isArray(cited) || !Array.isArray(excluded) || !Array.isArray(unaccounted)) return false
  if (!given.every(work) || !unaccounted.every(work) || !cited.every(s => typeof s === 'string')) return false
  if (!excluded.every(e => work(e) && typeof e.reason === 'string' && Object.hasOwn(LEDGER_REASONS, e.reason) && typeof e.note === 'string'
    && (e.same_as === null || e.same_as === undefined || work(e.same_as)))) return false
  const ids = given.map(g => g.source_version_id as string)
  const parts = [...cited as string[], ...excluded.map(e => e.source_version_id as string), ...unaccounted.map(u => u.source_version_id as string)]
  return new Set(ids).size === ids.length && new Set(parts).size === parts.length && parts.length === ids.length && parts.every(p => ids.includes(p))
}
// Ledger text in the Markdown file is data: Markdown and HTML characters are escaped, and a note's line breaks stay
// inside its one list item (hard breaks, indented), so a note cannot open a heading, a link, a tag or a section.
function markdownText(text: string) {
  return text.split(/\r\n|\r|\n/).map(line => line.trim()).filter(Boolean)
    .map(line => line.replace(/[\\`*_{}[\]()<>#|~&!=]/g, '\\$&').replace(/^([+-])/, '\\$1').replace(/^(\d+)([.)])/, '$1\\$2'))
    .join('  \n  ')
}

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
  // A citation is written in the chosen style ("Zeng et al., 2022"), else names its source's key (D59), else null (the
  // caller uses the reference number); a claim citing two passages of one source adds each passage's place.
  const citeLabel = (claim: Answer['claims'][number], e: Evidence): string | null => {
    if (style === 'ieee') return null
    const repeated = claim.evidence.filter(x => x.source_version_id === e.source_version_id).length > 1
    const locator = repeated ? (e.kind === 'abstract' ? t('abstract') : e.physical_page ? pageLocator(e.physical_page, e.rendition) : t('section')) : undefined
    const source = style && sources.find(s => s.source_version_id === e.source_version_id)
    const styled = source ? inTextCitation(style, source, locator) : null
    if (styled) return styled
    if (!e.source_key) return null
    return locator ? `${e.source_key}, ${locator}` : e.source_key
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
      const citations = claim.evidence.map(e => { const label = citeLabel(claim, e); return label ? `(${label})` : `[${refs.get(e.passage_id)?.n}]` }).join('')
      const inference = claim.support_type === 'analyst_inference' ? ` _(${t('interpretation')})_` : ''
      const review = claim.review ? ` _${t('Reviewer: {reason}', { reason: `${t(verdictLabels[claim.review.verdict])} — ${claim.review.reason}` })}_` : ''
      lines.push(`${claim.text}${citations ? ` ${citations}` : ''}${inference}${review}`, '')
    })
  })
  if (!answer.claims.length) lines.push(t('No claim could be linked to the passages given to the model.'), '')
  if (answer.unanswered_aspects.length) lines.push(`## ${t('Not answered by the inspected passages')}`, '', ...answer.unanswered_aspects.map(item => `- ${item}`), '')
  if (ledgerOk(answer.evidence_ledger)) {
    const rows = ledgerRows(answer.evidence_ledger)
    lines.push(`## ${t('Works given but not cited')}`, '', ledgerLine(answer.evidence_ledger), '')
    if (rows.length) lines.push(...rows.map(r => `- ${[markdownText(r.work.title ?? r.work.source_version_id), r.sameAs ? `${r.reason}: ${markdownText(r.sameAs)}` : r.reason,
      r.note && t('Note from the model: {note}', { note: markdownText(r.note) })].filter(Boolean).join(' · ')}`), '')
  }
  if (limits.length) lines.push(`## ${t('Limits')}`, '', ...limits.map(limit => `- **${t(limit.kind.replace('_', ' '))}:** ${limit.text}`), '')
  if (refs.size) {
    lines.push(`## ${t('Cited passages')}`, '')
    refs.forEach(({ n, e }) => {
      const source = sources.find(s => s.source_version_id === e.source_version_id)
      lines.push(`[${style === 'ieee' ? n : e.source_key ?? n}] ${source ? formatReferenceText(style, source) : e.title} — ${locatorText(e)}${e.text_source === 'ocr' ? ` (${t(OCR_LABEL)})` : ''}${e.text_source === 'latex_source' ? ` (${t('arXiv source')})` : ''}${e.text_source === 'equation_ocr' ? ` (${t('equations read by {name}', { name: equationReaderName(e.equation_reader ?? { engine: 'mathpix' }) })})` : ''}`)
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
