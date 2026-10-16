// One order for every read or write of a connection's state (E7). A request takes a ticket when it starts and may apply its
// answer only if no later ticket was handed out for that connection, or applied, before it came back: the all-connections
// read and the single-connection check share it, so a late older answer never covers a newer one.
export function createRequestOrder() {
  let clock = 0
  const latest: Record<string, number> = {}
  return {
    start(id?: string): number {
      const n = ++clock
      if (id !== undefined) latest[id] = n
      return n
    },
    // True once, for the answer that may be shown; false for an answer a later request has overtaken.
    settle(id: string, n: number): boolean {
      if ((latest[id] ?? 0) > n) return false
      latest[id] = n
      return true
    },
  }
}
