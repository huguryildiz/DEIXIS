import type { ReactNode } from 'react'
import { CircleX, Info, TriangleAlert } from 'lucide-react'

// An inline notice in one of three states: a blocking error (red), something that needs attention (amber), or plain
// information (neutral). The icon repeats the state; the text says what happened and what to do.
export function Notice({ tone, children }: { tone: 'error' | 'attention' | 'info'; children: ReactNode }) {
  const Icon = tone === 'error' ? CircleX : tone === 'attention' ? TriangleAlert : Info
  return <div className={`notice is-${tone}`} role={tone === 'error' ? 'alert' : undefined}><Icon size={15} aria-hidden /><div>{children}</div></div>
}
