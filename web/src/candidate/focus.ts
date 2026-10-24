import { useCallback, useEffect, useRef } from 'react'

export function useReturnFocus() {
  const returnFocus = useRef<HTMLElement | null>(null)
  const resolve = useRef<(() => HTMLElement | null) | null>(null)
  const frame = useRef<number | null>(null)
  useEffect(() => () => { if (frame.current !== null) cancelAnimationFrame(frame.current) }, [])
  const rememberFocus = useCallback((control: HTMLElement, currentControl?: () => HTMLElement | null) => {
    if (frame.current !== null) { cancelAnimationFrame(frame.current); frame.current = null }
    returnFocus.current = control
    resolve.current = currentControl ?? (() => control)
  }, [])
  const restoreFocus = useCallback(() => {
    if (frame.current !== null) cancelAnimationFrame(frame.current)
    // Wait until React has removed the modal's inert boundary and attached any replacement opener.
    frame.current = requestAnimationFrame(() => {
      frame.current = null
      const control = resolve.current?.() ?? returnFocus.current
      if (control?.isConnected) { returnFocus.current = control; control.focus({ preventScroll: true }) }
    })
  }, [])
  return { returnFocus, rememberFocus, restoreFocus }
}
