import type { ResearchView, Source } from '../lib/api'

// The included records and what an answer can read of each, for the panel's boxes and the thread's next step.
export function includedReading(view: ResearchView) {
  const byId = new Map(view.sources.map(s => [s.source_version_id, s]))
  const records = view.sources.filter(s => s.version_role === 'record' && s.selection.state === 'included')
  // The version an answer reads: the record, or another version with PDF text (D48).
  const reading = (record: Source) => (record.answer_reads_version_id ? byId.get(record.answer_reads_version_id) ?? record : record)
  // A work whose only PDF text is a person's file the model has not read yet gives an answer nothing (slice 18b).
  const full = (record: Source) => !record.answer_reads_nothing && reading(record).has_pdf_text
  return { records, reading, full, missing: records.filter(r => !full(r) && !r.answer_reads_nothing), unread: records.filter(r => r.answer_reads_nothing) }
}
