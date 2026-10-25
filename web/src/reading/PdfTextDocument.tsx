import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight, Quote, ScanText, TriangleAlert } from 'lucide-react'
import { Tooltip } from '@/components/ui/tooltip'
import { api, figureUrl, type AssetFigure } from '../lib/api'
import { t } from '../lib/i18n'
import { PassageMathText } from './PassageMathText'
import { OCR_LABEL } from './ocr'
import { IN_TEXT, SUBSECTION, buildDocument, locateAnchors, marksExactly, tableKey, type Doc, type Passages } from './pdfDocument'
import { scrollBehavior } from '../lib/motion'
import { pageLocator } from '../lib/labels'

// The extracted text of a whole PDF as a readable document (D58): section contents, pictures of figures cut from the PDF
// page, and in-text references to figures, tables, equations and numbered references that jump to them. Footnote markers are
// not linked: the text layer drops superscripts, and on the stored library no marker could be found (D58).
// Everything is found from the stored text with patterns (pdfDocument.ts); what a pattern misses stays plain text.

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

// An algorithm box: its steps line by line as read from the PDF, beside a picture of the box cut from the page, which keeps
// the symbols (accents, primes, subscripts) the reading spreads over loose characters.
function AlgorithmBox({ id, caption, lines, picture, cited, markLabel }: { id: string; caption?: string; lines: string[]; picture: { url: string; width: number; height: number; page: number } | null; cited: boolean; markLabel: string }) {
  const name = caption || t('Algorithm')
  return <figure id={id} className={`pdf-text-figure pdf-text-algorithm${cited ? ' is-cited' : ''}`} aria-label={cited ? markLabel : undefined}>
    {caption && <figcaption><PassageMathText text={caption} /></figcaption>}
    <div className={`pdf-text-algorithm-body${lines.length && picture ? ' is-split' : ''}`}>
      {lines.length > 0 && <div className="pdf-text-algorithm-lines">{lines.map((line, i) => <div key={i}><PassageMathText text={line} /></div>)}</div>}
      {picture && <img src={picture.url} alt={name} loading="lazy" style={{ aspectRatio: `${picture.width} / ${picture.height}` }} />}
    </div>
    {picture && <small>{t(lines.length ? 'Picture cut from PDF page {page}. The lines beside it are the text as read and can misplace symbols; the picture shows them as printed.' : 'Picture cut from PDF page {page}.', { page: picture.page })}</small>}
  </figure>
}

// The strip's two sentences and the mark's name, for a text opened for something other than an answer's citation (the
// human queue). Such a text is marked exactly or not at all: a span that would widen to a formula, or that falls in a
// title, heading, table or figure, is left unmarked rather than marked beyond what the backend found (slice 17).
// heading and go: the card's name and its button, when the text is opened for something other than a citation (D80).
export type CitationLabels = { marked: string; unmarked: string; mark: string; heading?: string; go?: string }

// "Cited passage i of N" in the cited-passage card: which marked place the reader is at, the exact text marked there
// (read back from the marks on the page, never composed), and how to step to another place.
export type CiteNav = { at: number; count: number; quote: string | null; onStep: (index: number) => void }

// With a citation, the document opens on the cited text: every located anchor is marked and the first is scrolled into view.
// An anchor not found in its page's text leaves the page unmarked; the view then opens on that page and says so.
export function PdfTextDocument({ researchId, assetId, passages, showNotes, sourceTitle = null, citation = null, rendition = false, comparison = false, suppressFigurePictures = false, label = null, nav = null }: { researchId: string; assetId: string; passages: Passages; showNotes: boolean; sourceTitle?: string | null; rendition?: boolean; comparison?: boolean; suppressFigurePictures?: boolean; label?: ReactNode; nav?: CiteNav | null; citation?: { page: number | null; texts: string[]; expected: boolean; labels?: CitationLabels } | null }) {
  const [figures, setFigures] = useState<AssetFigure[]>([])
  useEffect(() => {
    if (suppressFigurePictures) return
    let cancelled = false
    api.assetFigures(researchId, assetId).then(value => { if (!cancelled) setFigures(value.figures) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [researchId, assetId, suppressFigurePictures])
  const doc = useMemo(() => buildDocument(passages, suppressFigurePictures ? [] : figures, sourceTitle, suppressFigurePictures), [passages, figures, sourceTitle, suppressFigurePictures])
  const marks = useMemo(() => {
    if (!citation || comparison) return null
    const found = locateAnchors(doc, citation.page, citation.texts)
    return citation.labels && !marksExactly(doc, found, citation.texts) ? { blocks: new Map(), first: null, located: 0 } : found
  }, [doc, citation, comparison])
  const markLabel = citation?.labels?.mark ?? t(MARK_LABEL)
  const citedPage = citation ? doc.pages.find(p => p.head.physical_page === citation.page)?.head.id ?? null : null
  const unmarked = Boolean(!comparison && citation && (citation.texts.length ? marks!.located === 0 : citation.expected))
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

  // The outline rail (wide panels): each section heading with its page, the sections that hold a cited mark, and a map of
  // the pages with the cited ones marked. Everything comes from the document and the located marks.
  const outline = useMemo(() => {
    const headingIds = new Set(doc.headings.map(h => h.id))
    const pageOf = new Map<string, number | null>()
    const citedSections = new Set<string>()
    const citedPages = new Set<string>(citedPage ? [citedPage] : [])
    let current: string | null = null
    for (const { head, blocks } of doc.pages) for (const block of blocks) {
      if (headingIds.has(block.id)) { current = block.id; pageOf.set(block.id, head.physical_page) }
      if (marks?.blocks.has(block.id)) { citedPages.add(head.id); if (current) citedSections.add(current) }
    }
    return { pageOf, citedSections, citedPages }
  }, [doc, marks, citedPage])
  const [allSections, setAllSections] = useState(false)
  const railSections = allSections ? doc.headings : doc.headings.slice(0, 5)
  const pageCount = new Set(passages.map(item => item.physical_page)).size
  const meta = [rendition ? t('Drawn from Europe PMC') : null, t(pageCount === 1 ? '{n} page' : '{n} pages', { n: pageCount }), doc.headings.length ? t(doc.headings.length === 1 ? '{n} section' : '{n} sections', { n: doc.headings.length }) : null].filter(Boolean).join(' · ')
  const hasRail = doc.headings.length >= 3 || doc.pages.length > 1
  const pageName = (page: number | null) => page ? pageLocator(page, rendition) : t('Extracted text')

  const locator = citation ? pageLocator(citation.page ?? '?', rendition) : ''
  const quoted = Boolean(nav?.quote && !unmarked && !comparison)
  // A text opened for the human queue keeps its own sentence ("The model’s quote, found in the text of …") beside the quote.
  const noted = !quoted || Boolean(citation?.labels)
  const cardBody = comparison ? t('Current text · {locator} · not the cited extraction', { locator })
    : citation?.labels ? (unmarked ? citation.labels.unmarked : citation.labels.marked)
    : unmarked ? t(citation?.texts.length ? 'The cited text was not found in the text of {locator}, so it is not marked. Check the page in the PDF.' : 'This saved citation has no exact text anchor, so it cannot be highlighted. Generate a new answer to repair its citation anchors.', { locator })
    : t('Cited text · {locator}', { locator })

  return <div className={`sd-doc${marks?.located ? ' has-cite' : ''}`}>
    <div className="sd-main">
    {citation && <div className={`pdf-text-citation${unmarked ? ' is-unmarked' : ''}${comparison ? ' is-comparison' : ''}`}>
      {!comparison && <div className="cite-head">
        {unmarked ? <TriangleAlert size={15} aria-hidden /> : <Quote size={15} aria-hidden />}
        <span className="cite-label">{citation.labels?.heading ?? t('Cited passage')}</span>
        <span className="cite-meta">{nav && nav.count > 0 && !unmarked ? `${nav.at + 1} / ${nav.count} · ${locator}` : locator}</span>
        <span className="cite-spacer" />
        {nav && nav.count > 0 && <>
          <button type="button" className="cite-step" aria-label={t('Previous passage')} title={t('Previous passage')} disabled={nav.count < 2} onClick={() => nav.onStep(nav.at - 1)}><ChevronLeft size={14} aria-hidden /></button>
          <button type="button" className="cite-step" aria-label={t('Next passage')} title={t('Next passage')} disabled={nav.count < 2} onClick={() => nav.onStep(nav.at + 1)}><ChevronRight size={14} aria-hidden /></button></>}
      </div>}
      {quoted && <p className="cite-quote">“{nav!.quote}”</p>}
      {noted && <p className="cite-note">{cardBody}</p>}
      {(marks?.first || citedPage) && <div className="cite-foot"><button type="button" className="cite-go" onClick={goToCitation}>{!comparison && citation.labels?.go ? citation.labels.go : t(comparison ? 'Go to page' : marks?.first ? 'Go to cited text' : 'Go to cited page')}</button></div>}
    </div>}
    {label && <h3 className="source-section sd-label"><span className="sd-label-title">{label}</span><span className="sd-label-meta">{meta}</span></h3>}
    {doc.headings.length >= 3 && <details className="pdf-text-contents">
      <summary>{t('Contents · {n} sections', { n: doc.headings.length })}</summary>
      <ol>{doc.headings.map(h => <li key={h.id}><button type="button" onClick={() => jump(h.id)}>{h.text}</button></li>)}</ol>
    </details>}
    {doc.pages.map(({ head, blocks }) => {
      return <section className={`pdf-text-page${unmarked && head.id === citedPage ? ' is-cited-page' : ''}`} key={head.id} id={head.id}>
        <h4>{head.physical_page ? pageLocator(head.physical_page, rendition) : t('Extracted text')}{head.text_source === 'ocr' && <span className="ref-pill is-ocr"><ScanText size={12} aria-hidden />{t(OCR_LABEL)}</span>}</h4>
        {(head.equations_to_check ?? 0) > 0 && <p className="source-notice"><TriangleAlert size={15} aria-hidden />{t(head.equations_to_check === 1 ? '{n} equation on this page does not match the PDF’s own text and may be misread; check it against the PDF page.' : '{n} equations on this page do not match the PDF’s own text and may be misread; check them against the PDF page.', { n: head.equations_to_check ?? 0 })}</p>}
        {blocks.map(block => {
          const blockMarks = marks?.blocks.get(block.id)
          const inline = <InlineText text={block.text} doc={doc} selfId={block.id} marks={blockMarks} markLabel={markLabel} />
          const plainText = blockMarks ? <mark className="citation-highlight" aria-label={markLabel}>{block.text}</mark> : block.text
          const figure = block.kind === 'figure' || block.kind === 'algorithm' ? figures.find(f => f.label === block.label) : undefined
          if (block.kind === 'algorithm') return <AlgorithmBox key={block.id} id={block.id} caption={block.caption} lines={block.lines ?? []}
            picture={figure && !suppressFigurePictures ? { url: figureUrl(researchId, assetId, figure.label), width: figure.width, height: figure.height, page: figure.page } : null}
            cited={Boolean(blockMarks)} markLabel={markLabel} />
          return block.kind === 'figure' && suppressFigurePictures ? <figure key={block.id} id={block.id} className="pdf-text-figure">
            <figcaption>{inline}</figcaption><small>{t('Figure picture not shown: it would be cut from the current file, not the cited extraction.')}</small>
          </figure> : block.kind === 'figure' && figure ? <figure key={block.id} id={block.id} className="pdf-text-figure">
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
    </div>
    {hasRail && <aside className="sd-rail" aria-label={t('Contents')}>
      {doc.headings.length >= 3 && <div className="sd-rail-block">
        <h4 className="sd-rail-label">{t('Contents')}</h4>
        <ul className="sd-rail-list">{railSections.map(h => <li key={h.id}><button type="button" className={`sd-rail-item${outline.citedSections.has(h.id) ? ' is-cited' : ''}`} onClick={() => jump(h.id)}>
          <span className="sd-rail-text">{h.text}</span>{outline.citedSections.has(h.id) && <i className="sd-rail-dot" aria-hidden />}
          <span className="sd-rail-page">{pageName(outline.pageOf.get(h.id) ?? null)}</span></button></li>)}</ul>
        {doc.headings.length > 5 && <button type="button" className="sd-rail-more" onClick={() => setAllSections(v => !v)}>{allSections ? t('Show fewer sections') : t('+ {n} more sections', { n: doc.headings.length - 5 })}</button>}
      </div>}
      {doc.pages.length > 1 && <div className="sd-rail-block sd-map">
        <h4 className="sd-rail-label">{t('Citation map')}</h4>
        <div className="sd-map-grid">{doc.pages.map(({ head }) => <button key={head.id} type="button" className={`sd-map-cell${outline.citedPages.has(head.id) ? ' is-cited' : ''}`} title={pageName(head.physical_page)} aria-label={`${pageName(head.physical_page)}${outline.citedPages.has(head.id) ? ` · ${citation?.labels?.heading ?? t('Cited passage')}` : ''}`} onClick={() => jump(head.id)} />)}</div>
        <p className="sd-map-note">{t('Each box is a PDF page. Yellow: a page with a cited passage.')}</p>
      </div>}
    </aside>}
  </div>
}
