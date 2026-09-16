import type { Asset, OcrTool, Run } from './api'
import { t } from './i18n'

// Reading a PDF's pages without text with the local Tesseract (D51): when the action is offered, why it is off, and
// the progress of its run. OCR text is never shown as checked text; the label says to compare it with the page.

export const OCR_LABEL = 'OCR text · check against the page'

const ACTIVE = new Set(['queued', 'running', 'pause_requested', 'paused'])
const languageNames: Record<string, string> = { eng: 'English', tur: 'Turkish' }
export const ocrLanguagesText = (languages: string[]) => languages.map(l => t(languageNames[l] ?? l)).join(' + ')

export type OcrOffer =
  // blocked: another run of this research is working; the endpoint refuses a second one.
  | { kind: 'ready'; pages: number; tool: OcrTool; blocked: boolean }
  | { kind: 'off'; reason: string }
  | { kind: 'reading'; run: Run; done: number; total: number | null }

export function ocrOffer(asset: Asset, tool: OcrTool | null, runs: Run[]): OcrOffer | null {
  const ocr = asset.ocr
  if (!ocr || !ocr.pages_without_text || asset.extraction_status === 'succeeded' || asset.extraction_status === 'failed') return null
  const run = runs.find(r => r.kind === 'pdf_ocr' && r.target?.asset_id === asset.id && ACTIVE.has(r.status))
  if (run) {
    const steps = run.steps ?? []
    const found = steps.find(s => s.kind === 'ocr_pages')?.output?.image_pages
    return { kind: 'reading', run, done: steps.filter(s => s.kind === 'ocr_page' && s.status === 'succeeded').length, total: found ? found.length : null }
  }
  if (!tool) return null
  // A reading with this Tesseract version and these languages is not repeated (the endpoint answers 409).
  const last = ocr.last_read
  if (last && last.version === tool.version && last.languages.join('+') === tool.languages.join('+')) return null
  if (!tool.available) return { kind: 'off', reason: tool.reason ?? t('Tesseract is not available.') }
  return { kind: 'ready', pages: ocr.pages_without_text, tool, blocked: runs.some(r => ACTIVE.has(r.status) && r.status !== 'paused') }
}
