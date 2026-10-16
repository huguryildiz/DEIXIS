// One order for every read or write of a connection's state (E7). A request takes a ticket when it starts and may apply its
// answer only if no later ticket was handed out for that connection, or applied, before it came back. A ticket for the
// all-connections read (no id) counts for every connection from the moment it starts, so a single check that began before
// it and answers while it is still pending is dropped too. A read that was cancelled or timed out never answered: its ticket
// is released and stops holding back an older request that is still pending (E25).
export function createRequestOrder() {
  let clock = 0
  const issued: { n: number; id?: string }[] = []
  const released = new Set<number>()
  const applied: Record<string, number> = {}
  return {
    start(id?: string): number {
      const n = ++clock
      issued.push({ n, id })
      return n
    },
    release(n: number): void { released.add(n) },
    // True once, for the answer that may be shown; false for an answer a later request has overtaken.
    settle(id: string, n: number): boolean {
      if ((applied[id] ?? 0) > n) return false
      if (issued.some(x => x.n > n && !released.has(x.n) && (x.id === id || x.id === undefined))) return false
      applied[id] = n
      return true
    },
  }
}
