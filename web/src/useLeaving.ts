import { useCallback, useEffect, useRef } from 'react'

/** One signal per mounted page, fired when the page unmounts; hand it to a read so leaving cancels it (E25). The signal is
 *  made on first use, so a page that mounts again after a Strict Mode cleanup gets a fresh one. */
export function useLeaving(): () => AbortSignal {
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => { controller.current?.abort(); controller.current = null }, [])
  return useCallback(() => (controller.current ??= new AbortController()).signal, [])
}
