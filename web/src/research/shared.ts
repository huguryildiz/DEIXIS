import type { OcrTool, Run, Source } from '../lib/api'

// What the Sources rows need to offer OCR (D51): the local tool, the runs that may be reading a PDF, and the action.
export type OcrContext = { tool: OcrTool | null; runs: Run[]; onRead: (source: Source, assetId: string) => void }
