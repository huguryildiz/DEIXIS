import { createContext } from 'react'
import type { ResearchView } from './api'

export const TextRecoveryContext = createContext<{
  researchId: string; eventCursor: number; busy: boolean; acceptView: (view: ResearchView) => void; reload: () => Promise<void>
} | null>(null)
