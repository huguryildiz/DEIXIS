import { useCallback, useSyncExternalStore } from 'react'
import { ApiError } from '../api'

export type WriteCommand = { key: string; body: string }
// Keep an uncertain command across mode changes and sheet dismissal. Only an HTTP answer releases its key and body.
const unresolved = new Map<string, WriteCommand>()
const inFlight = new Set<string>()
const listeners = new Map<string, Set<() => void>>()
const notify = (identity: string) => listeners.get(identity)?.forEach(listener => listener())
export const pendingCommand = (identity: string) => unresolved.get(identity)
export const newCommand = (body: unknown, key: string = crypto.randomUUID()): WriteCommand => ({ key, body: JSON.stringify(body) })

export function useWriteCommand<T>(identity: string, request: (command: WriteCommand) => Promise<T>, success: (result: T) => void | Promise<void>, refused: (error: ApiError) => void | Promise<void>) {
  const subscribe = useCallback((listener: () => void) => {
    const group = listeners.get(identity) ?? new Set<() => void>()
    group.add(listener); listeners.set(identity, group)
    return () => { group.delete(listener); if (!group.size) listeners.delete(identity) }
  }, [identity])
  const pending = useSyncExternalStore(subscribe, () => unresolved.get(identity) ?? null)
  const busy = useSyncExternalStore(subscribe, () => inFlight.has(identity))
  const send = async (next?: WriteCommand) => {
    if (inFlight.has(identity)) return
    const command = unresolved.get(identity) ?? next
    if (!command) return
    unresolved.set(identity, command); inFlight.add(identity); notify(identity)
    let result: T
    try { result = await request(command) }
    catch (error) {
      inFlight.delete(identity)
      if (error instanceof ApiError) {
        unresolved.delete(identity); notify(identity)
        await refused(error)
      } else notify(identity)
      return
    }
    unresolved.delete(identity); inFlight.delete(identity); notify(identity)
    await success(result)
  }
  return { pending, busy, send, retry: () => send() }
}
