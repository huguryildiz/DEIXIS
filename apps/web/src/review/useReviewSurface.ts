import { useCallback, useMemo, useRef, useState } from 'react'

// The review dialog and panel of one target (P32/P33); the owner keeps this state and ReviewSurface draws both.
export type ReviewSurfaceState = ReturnType<typeof useReviewSurface>

export function useReviewSurface() {
  const [dialog, setDialog] = useState(false)
  const [panel, setPanel] = useState<{ id: string | null } | null>(null)
  const trigger = useRef<HTMLElement | null>(null)
  const openDialog = useCallback((opener?: HTMLElement | null) => {
    trigger.current = opener ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
    setDialog(true)
  }, [])
  const openPanel = useCallback((id: string | null = null) => setPanel({ id }), [])
  const closePanel = useCallback(() => setPanel(null), [])
  return useMemo(() => ({ dialog, setDialog, panel, openDialog, openPanel, closePanel, trigger }), [dialog, panel, openDialog, openPanel, closePanel])
}
