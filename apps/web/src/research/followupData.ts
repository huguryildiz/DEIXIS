import { useCallback, useEffect, useRef, useState } from 'react'
import { followupApi, type Claim, type Evidence, type FollowupClaim, type FollowupTurn, type Source } from '../api'

// The follow-up turns of a research (S22b) and their claims in the Citation panel's shape.

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// The turns of a research, read again whenever the research records an event. A list that was asked for before a newer
// one (or before a turn this page just queued) is dropped when it arrives, so an older answer never replaces a newer one.
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
  // A turn the server just returned for this page's own request.
  const accept = useCallback((turn: FollowupTurn) => {
    asked.current++
    setTurns(list => (list.some(item => item.id === turn.id) ? list.map(item => (item.id === turn.id ? turn : item)) : [...list, turn]))
  }, [])
  return { turns, error, reload: load, accept }
}

// A follow-up claim in the shape the Citation panel reads (P11): each citation keeps its stored passage, version, locator
// and backend-located anchor. Its id names the turn, so it never collides with a claim of the answer.
export const followupClaimId = (turn: FollowupTurn, claim: FollowupClaim) => `${turn.id}:${claim.label}`
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
