import { downloadName } from '../downloadName'
import { t } from '../i18n'

// The "PDF" rows of the export menus (plan §2.4, R8/P2/P30): DEIXIS writes no PDF itself, so the row opens the browser's
// print dialog on the open side panel, where "Save as PDF" writes the file from the panel as drawn (fonts, math and
// citation marks as on screen). `html[data-print="panel"]` tells print.css to print that panel alone; it is set just
// before the dialog opens and cleared when the browser says printing ended. Only the version the panel shows prints.
//
// `ready` is an element inside the open panel that shows its content is drawn (the report document). The row waits for
// it a short while (a panel just opened from the topbar menu renders on the next frames); false when it never came, so
// the caller says no dialog opened instead of printing an empty page.
// `name`: the document title while the dialog is open, which the browser offers as the PDF's file name.
export async function printPanel(ready: string, timeout = 4000, name?: (panel: Element) => string): Promise<boolean> {
  const started = performance.now()
  while (!document.querySelector(`[data-split-panel] ${ready}`)) {
    if (performance.now() - started > timeout) return false
    await new Promise(resolve => requestAnimationFrame(resolve))
  }
  await document.fonts?.ready
  // The panel may have changed while the fonts loaded (closed, or another report opened): print only if it still holds the target.
  if (!document.querySelector(`[data-split-panel] ${ready}`)) return false
  const root = document.documentElement
  const title = document.title
  const panel = document.querySelector(`[data-split-panel] ${ready}`)
  const done = () => { delete root.dataset.print; document.title = title; window.removeEventListener('afterprint', done) }
  if (name && panel) document.title = name(panel)
  root.dataset.print = 'panel'
  window.addEventListener('afterprint', done)
  window.print()
  return true
}

// The report's PDF row (S27): the print dialog on this version's open report panel; nothing is said to be saved, since
// the person saves (or not) in the dialog. When the panel did not show the report, no dialog opens and the toast says so.
export async function printReport(answerId: string, toast: (tone: 'error', text: string) => void) {
  const name = (panel: Element) => downloadName(panel.querySelector('h1')?.textContent ?? '', [`V${(panel as HTMLElement).dataset.version ?? ''}`], '', 'Report')
  if (!await printPanel(`.report-document[data-answer-id="${CSS.escape(answerId)}"]`, 4000, name)) toast('error', t('The report could not be shown for printing, so no print dialog opened.'))
}
