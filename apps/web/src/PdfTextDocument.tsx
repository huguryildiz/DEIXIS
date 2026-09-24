import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Quote, ScanText, TriangleAlert } from 'lucide-react'
import { Tooltip } from '@/components/ui/tooltip'
import { api, figureUrl, type AssetFigure } from './api'
import { t } from './i18n'
import { PassageMathText } from './PassageMathText'
import { OCR_LABEL } from './ocr'
import { SUBSECTION, buildDocument, locateAnchors, marksExactly, tableKey, type Doc, type Passages } from './pdfDocument'
import { scrollBehavior } from './motion'

// The extracted text of a whole PDF as a readable document (D58): section contents, pictures of figures cut from the PDF
// page, and in-text references to figures, tables, equations and numbered references that jump to them. Footnote markers are
// not linked: the text layer drops superscripts, and on the stored library no marker could be found (D58).
// Everything is found from the stored text with patterns (pdfDocument.ts); what a pattern misses stays plain text.

// "Fig. 3", "Figs. 3", "Figure 3", "Table II", "Eq. (5)", "Equation 5", "[12]", "[3, 5]", "[3–5]"
const IN_TEXT = /\b(Figs?\.|Figures?|FIGS?\.|Tables?|TABLE|Eqs?\.|Equations?)\s*\(?([IVXL]+(?![A-Za-z])|[A-Z]?\d{1,3})\)?|\[(\d{1,4}(?:\s*[,–-]\s*\d{1,4})*)\]/g

function jump(id: string) {
  const element = document.getElementById(id)
  if (!element) return
  element.scrollIntoView({ block: 'center', behavior: scrollBehavior() })
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

const MARK_LABEL = 'Exact text cited in the answer'

function InlineText({ text, doc, selfId, marks = [], markLabel = t(MARK_LABEL) }: { text: string; doc: Doc; selfId: string; marks?: [number, number][]; markLabel?: string }) {
  const math: [number, number][] = [...text.matchAll(/\$\$[\s\S]+?\$\$|\$[^$\n]+?\$/g)].map(m => [m.index!, m.index! + m[0].length])
  const inMath = (at: number) => math.some(([a, b]) => at >= a && at < b)
  // A mark never cuts a formula: it widens to the whole formula it touches.
  const marked = marks.map(([start, end]) => math.reduce<[number, number]>(([s, e], [a, b]) => a < e && b > s ? [Math.min(s, a), Math.max(e, b)] : [s, e], [start, end]))
  const markedAt = (at: number) => marked.some(([a, b]) => at >= a && at < b)
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
  const plain = (from: number, to: number) => {
    const cuts = [...new Set([from, to, ...marked.flat().filter(at => at > from && at < to)])].sort((a, b) => a - b)
    for (let i = 0; i + 1 < cuts.length; i++) {
      const piece = <PassageMathText key={`t${cuts[i]}`} text={text.slice(cuts[i], cuts[i + 1])} />
      parts.push(markedAt(cuts[i]) ? <mark key={`m${cuts[i]}`} className="citation-highlight" aria-label={markLabel}>{piece}</mark> : piece)
    }
  }
  let last = 0
  for (const match of matches) {
    if (match.start < last) continue
    if (match.start > last) plain(last, match.start)
    parts.push(markedAt(match.start) ? <mark key={`m${match.start}`} className="citation-highlight">{match.node}</mark> : match.node)
    last = match.end
  }
  if (last < text.length) plain(last, text.length)
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

// The strip's two sentences and the mark's name, for a text opened for something other than an answer's citation (the
// human queue). Such a text is marked exactly or not at all: a span that would widen to a formula, or that falls in a
// title, heading, table or figure, is left unmarked rather than marked beyond what the backend found (slice 17).
export type CitationLabels = { marked: string; unmarked: string; mark: string }

// With a citation, the document opens on the cited text: every located anchor is marked and the first is scrolled into view.
// An anchor not found in its page's text leaves the page unmarked; the view then opens on that page and says so.
export function PdfTextDocument({ researchId, assetId, passages, showNotes, sourceTitle = null, citation = null }: { researchId: string; assetId: string; passages: Passages; showNotes: boolean; sourceTitle?: string | null; citation?: { page: number | null; texts: string[]; expected: boolean; labels?: CitationLabels } | null }) {
  const [figures, setFigures] = useState<AssetFigure[]>([])
  useEffect(() => {
    let cancelled = false
    api.assetFigures(researchId, assetId).then(value => { if (!cancelled) setFigures(value.figures) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [researchId, assetId])
  const doc = useMemo(() => buildDocument(passages, figures, sourceTitle), [passages, figures, sourceTitle])
  const marks = useMemo(() => {
    if (!citation) return null
    const found = locateAnchors(doc, citation.page, citation.texts)
    return citation.labels && !marksExactly(doc, found, citation.texts) ? { blocks: new Map(), first: null, located: 0 } : found
  }, [doc, citation])
  const markLabel = citation?.labels?.mark ?? t(MARK_LABEL)
  const citedPage = citation ? doc.pages.find(p => p.head.physical_page === citation.page)?.head.id ?? null : null
  const unmarked = Boolean(citation && (citation.texts.length ? marks!.located === 0 : citation.expected))
  const goToCitation = () => {
    const block = marks?.first ? document.getElementById(marks.first) : null
    const target = block ? block.querySelector('mark') ?? block : citedPage ? document.getElementById(citedPage) : null
    target?.scrollIntoView({ block: 'center' })
  }
  const scrollKey = citation ? `${marks?.first}:${citedPage}` : null
  useEffect(() => {
    if (!scrollKey) return
    const frame = requestAnimationFrame(goToCitation)
    return () => cancelAnimationFrame(frame)
  }, [scrollKey])  // eslint-disable-line react-hooks/exhaustive-deps

  return <>
    {citation && <div className={`pdf-text-citation${unmarked ? ' is-unmarked' : ''}`}>
      {unmarked ? <TriangleAlert size={14} aria-hidden /> : <Quote size={14} aria-hidden />}
      <span>{citation.labels ? (unmarked ? citation.labels.unmarked : citation.labels.marked) : unmarked
        ? t(citation.texts.length ? 'The cited text was not found in the text of PDF p. {page}, so it is not marked. Check the page in the PDF.' : 'This saved citation has no exact text anchor, so it cannot be highlighted. Generate a new answer to repair its citation anchors.', { page: citation.page ?? '?' })
        : t('Cited text · PDF p. {page}', { page: citation.page ?? '?' })}</span>
      {(marks?.first || citedPage) && <button type="button" onClick={goToCitation}>{t(marks?.first ? 'Go to cited text' : 'Go to cited page')}</button>}
    </div>}
    {doc.headings.length >= 3 && <details className="pdf-text-contents">
      <summary>{t('Contents · {n} sections', { n: doc.headings.length })}</summary>
      <ol>{doc.headings.map(h => <li key={h.id}><button type="button" onClick={() => jump(h.id)}>{h.text}</button></li>)}</ol>
    </details>}
    {doc.pages.map(({ head, blocks }) => {
      return <section className={`pdf-text-page${unmarked && head.id === citedPage ? ' is-cited-page' : ''}`} key={head.id} id={head.id}>
        <h4>{head.physical_page ? t('PDF p. {page}', { page: head.physical_page }) : t('Extracted text')}{head.text_source === 'ocr' && <span className="ref-pill is-ocr"><ScanText size={12} aria-hidden />{t(OCR_LABEL)}</span>}</h4>
        {(head.equations_to_check ?? 0) > 0 && <p className="source-notice"><TriangleAlert size={15} aria-hidden />{t(head.equations_to_check === 1 ? '{n} equation on this page does not match the PDF’s own text and may be misread; check it against the PDF page.' : '{n} equations on this page do not match the PDF’s own text and may be misread; check them against the PDF page.', { n: head.equations_to_check ?? 0 })}</p>}
        {blocks.map(block => {
          const blockMarks = marks?.blocks.get(block.id)
          const inline = <InlineText text={block.text} doc={doc} selfId={block.id} marks={blockMarks} markLabel={markLabel} />
          const plainText = blockMarks ? <mark className="citation-highlight" aria-label={markLabel}>{block.text}</mark> : block.text
          const figure = block.kind === 'figure' ? figures.find(f => f.label === block.label) : undefined
          return block.kind === 'figure' && figure ? <figure key={block.id} id={block.id} className="pdf-text-figure">
            <img src={figureUrl(researchId, assetId, figure.label)} alt={block.text || t('Figure {n}', { n: figure.label })} loading="lazy" style={{ aspectRatio: `${figure.width} / ${figure.height}` }} />
            {block.text ? <figcaption>{inline}</figcaption> : <figcaption>{t('Figure {n}', { n: figure.label })}</figcaption>}
            <small>{t('Picture cut from PDF page {page}; it can miss part of the figure.', { page: figure.page })}</small>
          </figure>
            : block.kind === 'table' ? blockMarks ? <div key={block.id} id={block.id} className="pdf-text-table-cited" aria-label={markLabel}><PdfTextTable rows={block.text.split('\n')} /></div> : <PdfTextTable key={block.id} rows={block.text.split('\n')} />
            : block.kind === 'title' ? <h3 key={block.id} id={block.id} className="pdf-text-title">{plainText}</h3>
            : block.kind === 'heading' ? <h5 key={block.id} id={block.id} className={`pdf-text-heading${SUBSECTION.test(block.text) ? ' is-sub' : ''}`}>{plainText}</h5>
            : block.kind === 'note' ? (showNotes || blockMarks) && <p key={block.id} id={block.id} className="passage-text pdf-text-note">{inline}</p>
            : <p key={block.id} id={block.id} className={`passage-text${block.kind === 'bio' ? ' pdf-text-bio' : ''}`}>{inline}</p>
        })}
      </section>
    })}
  </>
}
