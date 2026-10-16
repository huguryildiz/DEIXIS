// A Settings read is cancelled when the page is left and ends with a "did not answer" error when it takes too long (E25).
// Writes never go through here: a save started before leaving keeps running and its result is kept.
export const READ_LIMIT_MS = 20_000
// A read that runs the CLIs or asks a service (the connections, a tool check) legitimately takes several seconds.
export const CHECK_LIMIT_MS = 60_000

/** Runs `run` with a signal that stops it when `leaving` fires (rejects with an AbortError) or when `ms` pass (rejects with `timedOut()`). */
export async function limited<T>(run: (signal: AbortSignal) => Promise<T>, leaving: AbortSignal | undefined, ms: number, timedOut: () => Error): Promise<T> {
  const controller = new AbortController()
  let late = false
  const timer = setTimeout(() => { late = true; controller.abort() }, ms)
  const stop = () => controller.abort()
  if (leaving?.aborted) controller.abort()
  else leaving?.addEventListener('abort', stop, { once: true })
  try {
    return await run(controller.signal)
  } catch (e) {
    if (late && !leaving?.aborted) throw timedOut()
    throw e
  } finally {
    clearTimeout(timer)
    leaving?.removeEventListener('abort', stop)
  }
}

/** True for a read that was cancelled because the page was left: nothing to show, nothing to report. */
export const isLeft = (e: unknown): boolean => e instanceof DOMException && e.name === 'AbortError'

/** True for a read that never produced an answer: cancelled by leaving, or out of time. */
export const gaveNoAnswer = (e: unknown): boolean => isLeft(e) || (e as { code?: unknown } | null)?.code === 'read_timed_out'
