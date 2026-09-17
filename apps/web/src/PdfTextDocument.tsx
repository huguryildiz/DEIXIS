import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ScanText, TriangleAlert } from 'lucide-react'
import { Tooltip } from '@/components/ui/tooltip'
import { api, figureUrl, type AssetFigure } from './api'
import { t } from './i18n'
import { PassageMathText } from './PassageMathText'
import { OCR_LABEL } from './ocr'
import { SUBSECTION, buildDocument, tableKey, type Doc, type Passages } from './pdfDocument'

// The extracted text of a whole PDF as a readable document (D58): section contents, pictures of figures cut from the PDF
// page, and in-text references to figures, tables, equations and numbered references that jump to them. Footnote markers are
// not linked: the text layer drops superscripts, and on the stored library no marker could be found (D58).
// Everything is found from the stored text with patterns (pdfDocument.ts); what a pattern misses stays plain text.

// "Fig. 3", "Figs. 3", "Figure 3", "Table II", "Eq. (5)", "Equation 5", "[12]", "[3, 5]", "[3–5]"
const IN_TEXT = /\b(Figs?\.|Figures?|FIGS?\.|Tables?|TABLE|Eqs?\.|Equations?)\s*\(?([IVXL]+(?![A-Za-z])|[A-Z]?\d{1,3})\)?|\[(\d{1,4}(?:\s*[,–-]\s*\d{1,4})*)\]/g

function jump(id: string) {
  const element = document.getElementById(id)
  if (!element) return
  element.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  element.classList.remove('is-jump-target')
  void element.offsetWidth
  element.classList.add('is-jump-target')
}

function referenceNumbers(list: string) {
  const numbers: string[] = []
  for (const part of list.split(/\s*,\s*/)) {
    const range = /^(\d+)\s*[–-]\s*(\d+)$/.exec(part)
    if (range && +range[2] > +range[1] && +range[2] - +range[1] <= 10) for (let n = +range[1]; n <= +range[2]; n++) numbers.push(String(n))
    else numbers.push(part.trim())
  }
  return numbers
}

function InlineText({ text, doc, selfId }: { text: string; doc: Doc; selfId: string }) {
  const math: [number, number][] = [...text.matchAll(/\$\$[\s\S]+?\$\$|\$[^$\n]+?\$/g)].map(m => [m.index!, m.index! + m[0].length])
  const inMath = (at: number) => math.some(([a, b]) => at >= a && at < b)
  const matches: { start: number; end: number; node: ReactNode }[] = []
  for (const m of text.matchAll(IN_TEXT)) {
    const start = m.index!
    if (inMath(start)) continue
    if (m[3]) {
      const numbers = referenceNumbers(m[3]).filter(n => doc.references.has(n))
      if (!numbers.length) continue
      const target = doc.targets.get(`ref:${numbers[0]}`)!
      if (target === selfId) continue  // a reference entry's own number
      matches.push({ start, end: start + m[0].length, node: <Tooltip key={start} className="pdf-text-tip" content={numbers.map(n => <span key={n} className="pdf-text-tip-entry">{doc.references.get(n)}</span>)}>
        <button type="button" className="pdf-text-xref" onClick={() => jump(target)}>{m[0]}</button>
      </Tooltip> })
      continue
    }
    const word = m[1].toLowerCase()
    const key = word.startsWith('fig') ? `figure:${m[2]}` : word.startsWith('tab') ? tableKey(m[2]) : `eq:${m[2]}`
    const target = doc.targets.get(key)
    if (!target || target === selfId) continue
    matches.push({ start, end: start + m[0].length, node: <button key={start} type="button" className="pdf-text-xref" onClick={() => jump(target)}>{m[0]}</button> })
  }
  matches.sort((a, b) => a.start - b.start)
  const parts: ReactNode[] = []
  let last = 0
  for (const match of matches) {
    if (match.start < last) continue
    if (match.start > last) parts.push(<PassageMathText key={`t${last}`} text={text.slice(last, match.start)} />)
    parts.push(match.node)
    last = match.end
  }
  if (last < text.length) parts.push(<PassageMathText key={`t${last}`} text={text.slice(last)} />)
  return <>{parts}</>
}

const cellsOf = (row: string) => row.slice(1, -1).split('|').map(cell => cell.trim())

// A Markdown table read by Marker (D54); its first row is the header when a |---| row follows it.
function PdfTextTable({ rows }: { rows: string[] }) {
  const header = rows.length > 1 && cellsOf(rows[1]).every(cell => /^:?-+:?$/.test(cell))
  const body = (header ? rows.slice(2) : rows).map(cellsOf)
  return <div className="pdf-text-table"><table>
    {header && <thead><tr>{cellsOf(rows[0]).map((cell, i) => <th key={i}><PassageMathText text={cell} /></th>)}</tr></thead>}
    <tbody>{body.map((cells, r) => <tr key={r}>{cells.map((cell, i) => <td key={i}><PassageMathText text={cell} /></td>)}</tr>)}</tbody>
  </table></div>
}

export function PdfTextDocument({ researchId, assetId, passages, showNotes, sourceTitle = null }: { researchId: string; assetId: string; passages: Passages; showNotes: boolean; sourceTitle?: string | null }) {
  const [figures, setFigures] = useState<AssetFigure[]>([])
  useEffect(() => {
    let cancelled = false
    api.assetFigures(researchId, assetId).then(value => { if (!cancelled) setFigures(value.figures) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [researchId, assetId])
  const doc = useMemo(() => buildDocument(passages, figures, sourceTitle), [passages, figures, sourceTitle])

  return <>
    {doc.headings.length >= 3 && <details className="pdf-text-contents">
      <summary>{t('Contents · {n} sections', { n: doc.headings.length })}</summary>
      <ol>{doc.headings.map(h => <li key={h.id}><button type="button" onClick={() => jump(h.id)}>{h.text}</button></li>)}</ol>
    </details>}
    {doc.pages.map(({ head, blocks }) => {
      return <section className="pdf-text-page" key={head.id}>
        <h4>{head.physical_page ? t('PDF p. {page}', { page: head.physical_page }) : t('Extracted text')}{head.text_source === 'ocr' && <span className="ref-pill is-ocr"><ScanText size={12} aria-hidden />{t(OCR_LABEL)}</span>}</h4>
        {(head.equations_to_check ?? 0) > 0 && <p className="source-notice"><TriangleAlert size={15} aria-hidden />{t(head.equations_to_check === 1 ? '{n} equation on this page does not match the PDF’s own text and may be misread; check it against the PDF page.' : '{n} equations on this page do not match the PDF’s own text and may be misread; check them against the PDF page.', { n: head.equations_to_check ?? 0 })}</p>}
        {blocks.map(block => {
          const inline = <InlineText text={block.text} doc={doc} selfId={block.id} />
          const figure = block.kind === 'figure' ? figures.find(f => f.label === block.label) : undefined
          return block.kind === 'figure' && figure ? <figure key={block.id} id={block.id} className="pdf-text-figure">
            <img src={figureUrl(researchId, assetId, figure.label)} alt={block.text || t('Figure {n}', { n: figure.label })} loading="lazy" style={{ aspectRatio: `${figure.width} / ${figure.height}` }} />
            {block.text ? <figcaption>{inline}</figcaption> : <figcaption>{t('Figure {n}', { n: figure.label })}</figcaption>}
            <small>{t('Picture cut from PDF page {page}; it can miss part of the figure.', { page: figure.page })}</small>
          </figure>
            : block.kind === 'table' ? <PdfTextTable key={block.id} rows={block.text.split('\n')} />
            : block.kind === 'title' ? <h3 key={block.id} id={block.id} className="pdf-text-title">{block.text}</h3>
            : block.kind === 'heading' ? <h5 key={block.id} id={block.id} className={`pdf-text-heading${SUBSECTION.test(block.text) ? ' is-sub' : ''}`}>{block.text}</h5>
            : block.kind === 'note' ? showNotes && <p key={block.id} id={block.id} className="passage-text pdf-text-note">{inline}</p>
            : <p key={block.id} id={block.id} className={`passage-text${block.kind === 'bio' ? ' pdf-text-bio' : ''}`}>{inline}</p>
        })}
      </section>
    })}
  </>
}
