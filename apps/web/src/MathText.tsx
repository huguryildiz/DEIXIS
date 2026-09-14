import type { ReactNode } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

// LaTeX in answer text (D19): $$…$$ is a displayed expression, $…$ an inline one. KaTeX escapes what it renders and,
// without `trust`, allows no links or HTML; an expression it cannot parse is drawn in red instead of throwing.
const MATH = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g

export function MathText({ text }: { text: string }) {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(MATH)) {
    const start = match.index ?? 0
    if (start > last) parts.push(text.slice(last, start))
    const display = match[1] !== undefined
    const html = katex.renderToString(display ? match[1] : match[2], { displayMode: display, throwOnError: false })
    parts.push(<span key={start} className={display ? 'math-display' : 'math-inline'} dangerouslySetInnerHTML={{ __html: html }} />)
    last = start + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}
