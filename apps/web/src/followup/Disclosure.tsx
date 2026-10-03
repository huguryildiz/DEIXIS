import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'

export function Disclosure({ title, children, onToggle }: { title: string; children: ReactNode; onToggle?: (open: boolean) => void }) {
  return <details className="followup-disclosure" onToggle={event => onToggle?.(event.currentTarget.open)}>
    <summary><ChevronRight size={14} aria-hidden />{title}</summary>{children}
  </details>
}
