import { useEffect, useState } from 'react'
import { type ResearchView } from '../api'

// The rail shows from 1100px (mockup `@media (max-width:1100px){.rail{display:none}}`); below it the panels are reached
// from the ⋯ menu (ResearchView), the answer and the keys.
export const RAIL_QUERY = '(min-width: 1100px)'
export function useRailWide() {
  const [wide, setWide] = useState(() => window.matchMedia(RAIL_QUERY).matches)
  useEffect(() => {
    const media = window.matchMedia(RAIL_QUERY)
    const onChange = () => setWide(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return wide
}

// Works whose two full-text passes both stored a result, over this question revision's runs: the count behind "Full text
// read". A work with one stored pass, or a failed one, is not counted (the same rule as the reading step's line).
export function fullTextRead(view: ResearchView): number {
  const passes = new Map<string, number>()
  for (const run of view.runs) {
    if (run.scope_revision !== view.research.current_scope_revision) continue
    for (const step of run.steps ?? []) {
      if (step.kind !== 'model:fulltext_adjudication') continue
      const work = step.operation_key.replace(/^fulltext_adjudication:/, '').replace(/:[^:]*$/, '')
      passes.set(work, (passes.get(work) ?? 0) + (step.status === 'succeeded' ? 1 : 0))
    }
  }
  return [...passes.values()].filter(n => n >= 2).length
}

// How deeply the sources an answer reads were read: PDF text, abstract only, or metadata only. A record whose own file has
// no text is counted by the other version an answer reads instead (D48).
export function depthOfIncluded(view: ResearchView) {
  const out = { pdf: 0, abstract: 0, metadata: 0 }
  for (const record of view.sources) {
    if (record.version_role !== 'record' || record.selection.state !== 'included') continue
    const read = record.answer_reads_version_id ? view.sources.find(s => s.source_version_id === record.answer_reads_version_id) ?? record : record
    if (read.has_pdf_text) out.pdf++
    else if (read.access.abstract_passage_id) out.abstract++
    else out.metadata++
  }
  return out
}
