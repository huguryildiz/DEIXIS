// One order for every read or write of a connection's state (E7). A request takes a ticket when it starts and may apply its
// answer only if no later ticket was handed out for that connection, or applied, before it came back. A ticket for the
// all-connections read (no id) counts for every connection from the moment it starts, so a single check that began before
// it and answers while it is still pending is dropped too.
export function createRequestOrder() {
  let clock = 0
  const latest: Record<string, number> = {}
  let allFrom = 0  // the newest all-connections ticket
  return {
    start(id?: string): number {
      const n = ++clock
      if (id === undefined) allFrom = n
      else latest[id] = n
      return n
    },
    // True once, for the answer that may be shown; false for an answer a later request has overtaken.
    settle(id: string, n: number): boolean {
      if ((latest[id] ?? 0) > n || allFrom > n) return false
      latest[id] = n
      return true
    },
  }
}
