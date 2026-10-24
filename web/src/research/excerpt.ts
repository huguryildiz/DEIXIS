// Shared by the Citation panel and the evidence report's citation panel (UI parity S15a).
// The passage text around the anchor: a page is long, so the quote shows about two sentences on each side of it.
const CONTEXT = 240
export function excerpt(text: string, anchor: string | null): { text: string; located: boolean } {
  const at = anchor ? text.indexOf(anchor) : -1
  if (at < 0) return { text: text.length > 2 * CONTEXT ? `${text.slice(0, 2 * CONTEXT).trimEnd()}…` : text, located: false }
  let start = Math.max(0, at - CONTEXT), end = Math.min(text.length, at + anchor!.length + CONTEXT)
  if (start > 0) { const space = text.indexOf(' ', start); start = space >= 0 && space < at ? space + 1 : at }
  if (end < text.length) { const space = text.lastIndexOf(' ', end); end = space > at + anchor!.length ? space : at + anchor!.length }
  return { text: `${start > 0 ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`, located: true }
}
