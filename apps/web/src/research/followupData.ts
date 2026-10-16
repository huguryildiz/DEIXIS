import { useCallback, useEffect, useRef, useState } from 'react'
import { followupApi, type Claim, type Evidence, type FollowupClaim, type FollowupTurn, type Source } from '../api'

// The follow-up turns of a research (S22b) and their claims in the Citation panel's shape.

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// The turns of a research, read again whenever the research records an event. A list that was asked for before a newer
// one is dropped when it arrives, so an older answer never replaces a newer one.
export function useFollowupTurns(researchId: string, eventCursor: number) {
  const [turns, setTurns] = useState<FollowupTurn[]>([])
  const [error, setError] = useState('')
  const asked = useRef(0)
  const load = useCallback(async () => {
    const n = ++asked.current
    try {
      const list = await followupApi.list(researchId)
      if (n === asked.current) { setTurns(list); setError('') }
    } catch (e) { if (n === asked.current) setError(errorText(e)) }
  }, [researchId])
  useEffect(() => { void load() }, [load, eventCursor])
  // A turn the server just queued for this page's own request: shown at once when the list does not hold it yet, never
  // in place of a copy the list already holds (a list read after the POST may already carry its answer), and the list is
  // read again, so a late POST response can neither hide an answer nor drop a newer list.
  const accept = useCallback((turn: FollowupTurn) => {
    setTurns(list => (list.some(item => item.id === turn.id) ? list : [...list, turn]))
    void load()
  }, [load])
  return { turns, error, reload: load, accept }
}

// A follow-up claim in the shape the Citation panel reads (P11): each citation keeps its stored passage, version, locator
// and backend-located anchor. Its id names the turn, so it never collides with a claim of the answer.
export const followupClaimId = (turn: FollowupTurn, claim: FollowupClaim) => `${turn.id}:${claim.label}`
// Each work of a group (D66) as a claim of its own, so its chip opens the Citation panel like a claim's: labelled by
// group and work, its text the work's title.
export const followupGroupClaims = (turn: FollowupTurn): FollowupClaim[] =>
  (turn.answer?.work_groups?.groups ?? []).flatMap((group, g) => group.works.map(work => ({
    label: `g${g + 1}:${work.work_id}`, text: `${group.label}: ${workTitle(work)}`, citations: work.citations,
    // A membership the model inferred, not one its passage states, is shown as an interpretation, as a claim is.
    support_type: !work.inference && work.citations.every(c => c.support_type === 'source_stated') ? 'source_stated' as const : 'analyst_inference' as const })))
export const workTitle = (work: { title: string | null; year: number | null }) =>
  `${work.title ?? ''}${work.year ? ` (${work.year})` : ''}`
export function followupClaim(turn: FollowupTurn, claim: FollowupClaim, sources: Source[]): Claim {
  return {
    id: followupClaimId(turn, claim), label: claim.label, section: null, text: claim.text, support_type: claim.support_type,
    semantic_review: '', review: null,
    evidence: claim.citations.map((c): Evidence => ({
      passage_id: c.passage_id, source_version_id: c.source_version_id, work_id: c.work_id,
      source_key: sources.find(s => s.source_version_id === c.source_version_id)?.source_key ?? null,
      kind: c.locator.kind as Evidence['kind'], physical_page: c.locator.physical_page, printed_label: c.locator.printed_label,
      reading_depth: c.reading_depth, title: c.title, version_label: c.version_label, anchor_text: c.anchor_text,
      evidence_status: c.evidence_status, text_source: c.text_source, removed_from_research: c.removed_from_research, rendition: c.rendition,
    })),
  }
}

// Passages the person added to the composer with "Add to chat" travel in the question itself as Markdown quote blocks
// ahead of the question, so the model reads them as quoted text and the server needs no new field.
export function withQuotes(quotes: string[], question: string) {
  const blocks = quotes.map(q => q.split('\n').map(line => `> ${line}`).join('\n'))
  return [...blocks, question].join('\n\n')
}

// The quote blocks at the start of a stored question and the question after them.
export function splitQuotes(question: string): { quotes: string[]; text: string } {
  const quotes: string[] = []
  const parts = question.split(/\n{2,}/)
  // An empty quote line is stored as a bare '>': the backend drops trailing spaces on each line.
  while (parts.length > 1 && parts[0].split('\n').every(line => line === '>' || line.startsWith('> '))) {
    quotes.push(parts.shift()!.split('\n').map(line => line.slice(2)).join('\n'))
  }
  return { quotes, text: parts.join('\n\n') }
}
