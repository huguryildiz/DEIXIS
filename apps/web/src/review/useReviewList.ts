import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type ReviewCard } from '../api'

export function useReviewList(researchId: string, kind: 'answer' | 'report', targetId: string, eventCursor: number, enabled = true) {
  const [reviews, setReviews] = useState<ReviewCard[]>([])
  const [error, setError] = useState('')
  const sequence = useRef(0)
  const refresh = useCallback(async () => {
    if (!enabled) return []
    const ticket = ++sequence.current
    try {
      const rows = await api.reviews(researchId, kind, targetId)
      if (ticket === sequence.current) { setReviews(rows); setError('') }
      return rows
    } catch (e) { if (ticket === sequence.current) setError(e instanceof Error ? e.message : String(e)); return [] }
  }, [researchId, kind, targetId, enabled])
  useEffect(() => { const ref = sequence; void Promise.resolve().then(refresh); return () => { ref.current++ } }, [refresh, eventCursor])
  return { reviews, error, refresh }
}
