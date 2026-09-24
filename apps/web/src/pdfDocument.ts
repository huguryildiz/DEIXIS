// Building the plain-text view of a PDF from its stored passages (D58): paragraphs, the title, section headings, tables,
// figures, biographies and the targets of in-text references. Pure functions, so the rules can be tested without a browser.
import type { AssetFigure, AssetText } from './api'
import { AUTHOR_NOTE, SECTION_HEADING, readablePassageText } from './pdfText'

export type Passages = AssetText['passages']

const TABLE_ROW = /^\|.*\|$/
const FIGURE_CAPTION = /^(?:Fig\.|FIG\.|Figure|FIGURE)\s*(\d{1,3})\s*(?:[.:|—–]|\s(?=[A-Z(]))/
const TABLE_CAPTION = /^(?:TABLE|Table)\s+([IVXL]+|[A-Z]?\d{1,3})\s*(?:$|[.:|—–-]|\s(?=[A-Z]))/
// An author biography at the end of a journal paper: "Jane Q. Doe (jdoe@x.edu) received …", "John Roe (M'05–SM'16) is …".
// Biographies follow the last reference entry, so the text layer runs them into it.
const BIOGRAPHY = /^[A-Z][\p{L}'’.-]+(?:\s[A-Z][\p{L}'’.-]*){1,3}\s(?:\([^()\s]+@[^()\s]+\)|\((?:[A-Z]+['’]?\d{2}[–-]?)+[^()]{0,20}\))?\s?(?:received|is|was|joined|has been|graduated)\b/u
const BIOGRAPHY_START = /(?<=[.”"])\s+(?=[A-Z][\p{L}'’.-]+(?:\s[A-Z][\p{L}'’.-]*){1,3}\s(?:\([^()\s]+@[^()\s]+\)|\((?:[A-Z]+['’]?\d{2}[–-]?)+[^()]{0,20}\))\s?(?:received|is|was|joined|has been|graduated)\b)/u
const REFERENCE_ENTRY = /^\[(\d{1,4})\]\s/
const EQUATION_TAG = /\\tag\{(\d{1,3})\}|\((\d{1,3})\)\s*\$*$/g

export type Block = { id: string; kind: 'heading' | 'table' | 'note' | 'para' | 'figure' | 'bio' | 'title'; text: string; label?: string }
export type Page = { head: Passages[number]; blocks: Block[] }
export type Doc = { pages: Page[]; targets: Map<string, string>; references: Map<string, string>; headings: Block[] }

function pagesOf(passages: Passages) {
  const pages: Passages[] = []
  for (const item of passages) {
    const last = pages[pages.length - 1]
    if (last && last[0].physical_page === item.physical_page) last.push(item)
    else pages.push([item])
  }
  return pages
}

// A numbered heading set in the same text block as the paragraph after it ("II. SYSTEM MODEL\nIn this study, …") becomes its
// own paragraph. The heading line must be in capitals, or at least two words in Title Case; a capital line that continues it
// ("… ROUTING PROTOCOLS FOR\nUWSNs") stays with it.
const HEADING_LINE = /(^|\n)((?:[IVXL]+|[1-9]\d?(?:\.\d+)*|[A-H])\.?[ \t]+[A-Z][^\n.,;:“”"[\]]{1,76})\n(?:([A-Z][^\n.,;:]{1,40})\n)?(?=[A-Z])/g
const SMALL_WORD = /^(?:a|an|and|as|at|by|for|from|in|into|of|on|or|the|to|with|via|vs\.?|versus)$/

function headingLike(line: string) {
  const letters = line.replace(/[^\p{L}]/gu, '')
  const capitals = letters.replace(/[^\p{Lu}]/gu, '').length / Math.max(1, letters.length)
  const words = line.split(/\s+/).slice(1)
  return capitals >= 0.8 || (words.length >= 2 && words.length <= 10 && words.every(w => /^[\p{Lu}\d(]/u.test(w) || SMALL_WORD.test(w)))
}

export function splitHeadingLines(text: string) {
  return text.replace(HEADING_LINE, (whole, start: string, line: string, more: string | undefined) => {
    if (!headingLike(line)) return whole
    const before = start ? '\n\n' : ''
    return more && headingLike(`X ${more}`) ? `${before}${line} ${more}\n\n` : `${before}${line}\n\n${more ? `${more}\n` : ''}`
  })
}

export function pageParagraphs(passages: Passages) {
  // Passages are cut at a fixed length; a cut that did not end a sentence, or one inside a reference entry, continues the paragraph.
  // Marker leaves its in-document links ("Figure [4a](#page-6-2)"); only their text is shown.
  const text = passages.map(item => readablePassageText(item.kind, splitHeadingLines(item.text)).replace(/\[([^\]\n]{1,40})\]\(#page-\d+-\d+\)/g, '$1')).reduce((all, next) => {
    const last = all.slice(all.lastIndexOf('\n\n') + 1).trim()
    const continues = !/[.:?!)]$/.test(last) || (/^\[\d{1,4}\]\s/.test(last) && !/^\[\d{1,4}\]\s/.test(next))
    // A passage cut after a table row starts a new row or, when it does not open with "|", a new paragraph (a caption).
    return !all ? next : all.endsWith('|') ? `${all}${next.startsWith('|') ? '\n' : '\n\n'}${next}` : continues ? `${all} ${next}` : `${all}\n\n${next}`
  }, '')
  return text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean).flatMap(paragraph => {
    // Table rows and the text around them become separate paragraphs.
    const runs: string[][] = []
    for (const line of paragraph.split('\n')) {
      const last = runs[runs.length - 1]
      if (last && TABLE_ROW.test(last[0]) === TABLE_ROW.test(line)) last.push(line)
      else runs.push([line])
    }
    return runs.map(run => run.join(TABLE_ROW.test(run[0]) ? '\n' : ' '))
  }).flatMap(paragraph => paragraph.split(BIOGRAPHY_START).map(p => p.trim()).filter(Boolean)).map((paragraph, i, all) => {
    // A drop capital read into the heading before it: "I. INTRODUCTION S" + "MART Grid (SG) is …" → "SMART Grid (SG) is …".
    const drop = /^(.+)\s(\p{Lu})$/u.exec(paragraph)
    if (drop && SECTION_HEADING.test(drop[1]) && /^\p{Lu}{2,}/u.test(all[i + 1] ?? '')) { all[i + 1] = drop[2] + all[i + 1]; return drop[1] }
    return paragraph
  })
}

// MuPDF sets each line of a large title, and each line of a long author list, as its own block. At the top of the first page,
// title lines are joined (the source's own title, or consecutive short Title Case lines without digits or commas) and an
// author line ending with a comma is joined to the next one.
const squash = (text: string) => text.toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
const TITLE_LINE = (text: string) => text.length <= 100 && !/[\d@,;:.?!*]/.test(text)
  && text.split(/\s+/).filter(w => /^\p{Lu}/u.test(w)).length >= Math.ceil(text.split(/\s+/).filter(w => w.length > 3).length * 0.8)

export function firstPage(original: string[], sourceTitle: string | null): { paragraphs: string[]; title: number } {
  // A journal header run into the title's first line ("IEEE TRANSACTIONS ON COMMUNICATIONS 1 End-to-End …") is split off.
  const opening = sourceTitle?.split(/\s+/).slice(0, 3).join(' ')
  const paragraphs = original.flatMap((text, i) => {
    const at = i < 6 && opening ? text.toLocaleLowerCase().replace(/\s+/g, ' ').indexOf(opening.toLocaleLowerCase()) : -1
    return at > 0 && text.replace(/\s+/g, ' ') === text ? [text.slice(0, at).trim(), text.slice(at)] : [text]
  })
  const head = paragraphs.slice(0, 6)
  const merge = (i: number, j: number) => {
    const merged = [...paragraphs.slice(0, i), head.slice(i, j + 1).join(' '), ...paragraphs.slice(j + 1)]
    return { paragraphs: joinAuthorLines(merged, i + 1), title: i }
  }
  const target = sourceTitle ? squash(sourceTitle) : ''
  if (target) for (let i = 0; i < head.length; i++) {
    for (let j = i; j < head.length && target.startsWith(squash(head.slice(i, j + 1).join(' '))); j++) {
      if (squash(head.slice(i, j + 1).join(' ')) === target) return merge(i, j)
    }
  }
  // The stored title differs from the PDF's (or is missing): the first run of two or more Title Case lines.
  for (let i = 0; i < Math.min(head.length, 3); i++) {
    let j = i
    while (j + 1 < head.length && TITLE_LINE(head[j]) && TITLE_LINE(head[j + 1])) j++
    if (j > i && !SECTION_HEADING.test(head.slice(i, j + 1).join(' '))) return merge(i, j)
  }
  return { paragraphs: original, title: -1 }
}

function joinAuthorLines(paragraphs: string[], from: number) {
  const out = paragraphs.slice(0, from)
  for (const [k, text] of paragraphs.slice(from).entries()) {
    const last = out[out.length - 1]
    if (k < 4 && out.length > from && last.endsWith(',') && !/^Abstract/i.test(text)) out[out.length - 1] = `${last} ${text}`
    else out.push(text)
  }
  return out
}

// The biographies heading DEIXIS adds is written in the paper's language and in the case of its other headings.
function biographyHeading(passages: Passages, headings: Block[]) {
  const sample = passages.slice(0, 4).map(p => p.text).join(' ').toLocaleLowerCase('tr')
  const count = (words: string[]) => words.reduce((n, w) => n + (sample.match(new RegExp(`\\s${w}\\s`, 'g'))?.length ?? 0), 0)
  const turkish = count(['ve', 'bir', 'için', 'ile', 'bu', 'olarak']) > count(['the', 'and', 'of', 'in', 'to', 'is'])
  const text = turkish ? 'Biyografiler' : 'Biographies'
  const capitals = headings.some(h => /^(?:REFERENCES|KAYNAKLAR|KAYNAKÇA)$/.test(h.text))
  return capitals ? text.toLocaleUpperCase(turkish ? 'tr' : 'en') : text
}

// "A. Model", "3.2 Results": a subsection, set smaller than a section ("II. MODEL", "3 Results", "REFERENCES").
export const SUBSECTION = /^(?:[A-H]|\d+\.\d+(?:\.\d+)*)\.?\s/

export const tableKey = (label: string) => `table:${label.toUpperCase()}`

export function buildDocument(passages: Passages, figures: AssetFigure[], sourceTitle: string | null): Doc {
  const targets = new Map<string, string>(), references = new Map<string, string>(), headings: Block[] = []
  const placed = new Set<string>()
  let biographies = 0
  const pages = pagesOf(passages).map((items, p) => {
    const top = p === 0 ? firstPage(pageParagraphs(items), sourceTitle) : { paragraphs: pageParagraphs(items), title: -1 }
    const blocks: Block[] = []
    top.paragraphs.forEach((text, i) => {
      const id = `pdfx-${p}-${i}`
      if (i === top.title) {
        blocks.push({ id, kind: 'title', text })
        return
      }
      const figure = FIGURE_CAPTION.exec(text)
      if (figure && !placed.has(figure[1]) && figures.some(f => f.label === figure[1])) {
        placed.add(figure[1])
        blocks.push({ id: `pdfx-fig-${figure[1]}`, kind: 'figure', text, label: figure[1] })
        targets.set(`figure:${figure[1]}`, `pdfx-fig-${figure[1]}`)
        return
      }
      const kind = text.split('\n').every(line => TABLE_ROW.test(line)) ? 'table' : SECTION_HEADING.test(text) ? 'heading' : BIOGRAPHY.test(text) && (biographies || references.size) ? 'bio' : AUTHOR_NOTE.test(text) ? 'note' : 'para'
      const previous = blocks[blocks.length - 1]
      if (kind === 'para' && previous?.kind === 'bio' && !FIGURE_CAPTION.test(text) && !TABLE_CAPTION.test(text)) {
        previous.text = `${previous.text} ${text}`  // a biography continued after a column or page break
        return
      }
      if (kind === 'bio' && !biographies++ && !/^(?:Author )?Biograph|^Biyografi/i.test(headings[headings.length - 1]?.text ?? '')) {
        const heading: Block = { id: 'pdfx-biographies', kind: 'heading', text: biographyHeading(passages, headings) }
        blocks.push(heading)
        headings.push(heading)
      }
      const block: Block = { id, kind, text }
      blocks.push(block)
      if (kind === 'heading' && !/^\d+\.0\s/.test(text)) headings.push(block)  // "1.0 BBPSSW" is a plot's axis text, not a section
      if (figure && !targets.has(`figure:${figure[1]}`)) targets.set(`figure:${figure[1]}`, id)
      const table = TABLE_CAPTION.exec(text)
      if (table && !targets.has(tableKey(table[1]))) targets.set(tableKey(table[1]), id)
      const reference = REFERENCE_ENTRY.exec(text)
      if (reference && !references.has(reference[1])) { references.set(reference[1], text); targets.set(`ref:${reference[1]}`, id) }
      if (kind === 'para' && text.length < 600) for (const m of text.matchAll(EQUATION_TAG)) {
        const n = m[1] ?? m[2]
        if (!targets.has(`eq:${n}`)) targets.set(`eq:${n}`, id)
      }
    })
    // A figure found on this page whose caption was not recognised in the text still shows, at the end of its page.
    for (const figure of figures.filter(f => f.page === items[0].physical_page && !placed.has(f.label))) {
      placed.add(figure.label)
      blocks.push({ id: `pdfx-fig-${figure.label}`, kind: 'figure', text: '', label: figure.label })
      if (!targets.has(`figure:${figure.label}`)) targets.set(`figure:${figure.label}`, `pdfx-fig-${figure.label}`)
    }
    return { head: items[0], blocks }
  })
  return { pages, targets, references, headings }
}

// Where citation anchors fall in the document built from a page (the plain-text view opened from a citation). Letters and
// digits are compared case-folded with spaces and punctuation ignored, as the server locates anchors (contracts.locate_anchor),
// so line breaks, hyphenation and the paragraph joins made above do not stop a match; a match may run across blocks.
export type AnchorMarks = { blocks: Map<string, [number, number][]>; first: string | null; located: number }

export function locateAnchors(doc: Doc, page: number | null, texts: string[]): AnchorMarks {
  const marks: AnchorMarks = { blocks: new Map(), first: null, located: 0 }
  const blocks = doc.pages.find(p => p.head.physical_page === page)?.blocks.filter(b => b.text) ?? []
  let compact = ''
  const spans: { block: number; start: number; end: number }[] = []
  blocks.forEach((block, i) => {
    for (const m of block.text.matchAll(/[\p{L}\p{N}]+/gu)) {
      const word = m[0].normalize('NFKC').toLocaleLowerCase()
      compact += word
      for (let k = 0; k < word.length; k++) spans.push({ block: i, start: m.index!, end: m.index! + m[0].length })
    }
  })
  for (const text of texts) {
    const quote = [...text.matchAll(/[\p{L}\p{N}]+/gu)].map(m => m[0].normalize('NFKC').toLocaleLowerCase()).join('')
    const at = quote ? compact.indexOf(quote) : -1
    if (at < 0) continue
    marks.located++
    const from = spans[at], to = spans[at + quote.length - 1]
    for (let b = from.block; b <= to.block; b++) {
      const block = blocks[b]
      const ranges = marks.blocks.get(block.id) ?? []
      ranges.push([b === from.block ? from.start : 0, b === to.block ? to.end : block.text.length])
      marks.blocks.set(block.id, ranges)
    }
  }
  marks.first = doc.pages.flatMap(p => p.blocks).find(b => marks.blocks.has(b.id))?.id ?? null
  return marks
}

// Whether the marks are exactly the given text and nothing more, for a text opened from the human queue (slice 17):
// only running text is marked span by span (a heading or table is marked whole, a formula as a whole), and a match
// that starts or ends inside a word widens to that word. Any of these leaves the text unmarked instead.
export function marksExactly(doc: Doc, marks: AnchorMarks, texts: string[]): boolean {
  const compact = (text: string) => [...text.matchAll(/[\p{L}\p{N}]+/gu)].map(m => m[0].normalize('NFKC').toLocaleLowerCase()).join('')
  let marked = ''
  for (const block of doc.pages.flatMap(p => p.blocks)) {
    const ranges = marks.blocks.get(block.id)
    if (!ranges) continue
    if (block.kind !== 'para' && block.kind !== 'note' && block.kind !== 'bio') return false
    const math = [...block.text.matchAll(/\$\$[\s\S]+?\$\$|\$[^$\n]+?\$/g)].map(m => [m.index!, m.index! + m[0].length])
    for (const [s, e] of ranges) {
      if (math.some(([a, b]) => a < e && b > s && (a < s || b > e))) return false
      marked += block.text.slice(s, e)
    }
  }
  return texts.length !== 1 || compact(marked) === compact(texts[0])
}
