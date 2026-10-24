import { createRequestOrder } from '../requestOrder'

// The order overlapping reads of one research's view are shown in (audit F5). An answer a later read has overtaken is
// kept, not shown: when that later read fails, its ticket is released and the kept answer is shown instead, so a failed
// read never hides an older view that did arrive. The failure itself is shown only when no later read has answered or
// is still pending.
export function createViewReads<V>() {
  const order = createRequestOrder()
  let kept: { id: string; ticket: number; view: V } | null = null
  return {
    start: (id: string) => order.start(id),
    // The view to show for this answer, or null when a later read overtook it.
    answered(id: string, ticket: number, view: V): V | null {
      if (order.settle(id, ticket)) {
        kept = null  // anything kept is older than what is now shown
        return view
      }
      if (!kept || kept.id !== id || kept.ticket < ticket) kept = { id, ticket, view }
      return null
    },
    // After a failed read: the kept view to show instead (or null), and whether the failure is the newest word.
    failed(id: string, ticket: number): { view: V | null; showError: boolean } {
      order.release(ticket)
      let view: V | null = null
      if (kept && kept.id === id && order.settle(id, kept.ticket)) {
        view = kept.view
        kept = null
      }
      return { view, showError: order.current(id, ticket) }
    },
  }
}
