import { createContext } from 'react'

// The place at the foot of the sidebar, above the access card, where the research page shows its latest run's status.
// Null on a phone (the sidebar is a drawer) and while the sidebar is collapsed: the status then stays in the topbar.
export const RunSlotContext = createContext<HTMLElement | null>(null)
