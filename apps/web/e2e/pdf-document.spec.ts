import { expect, test } from '@playwright/test'
import { buildDocument, locateAnchors, marksExactly, type Passages } from '../src/pdfDocument'

// The plain-text view's reading rules (D58) on SYNTHETIC page text; no browser or server is started.

let next = 0
function pages(...texts: string[][]): Passages {
  return texts.flatMap((chunks, p) => chunks.map(text => ({
    id: `psg_${next++}`, kind: 'pdf_page' as const, text, physical_page: p + 1, printed_label: null, extraction_version: null, payload_ref: null,
  })))
}
const blocks = (doc: ReturnType<typeof buildDocument>, page = 0) => doc.pages[page].blocks.map(b => [b.kind, b.text])

test('a title and an author list set line by line are joined, with or without the stored title', () => {
  const first = ['IEEE TRANSACTIONS ON SYNTHETIC NETWORKS 1\nSynthetic Packet Scheduling in\n\nMolecular Relay Networks\n\n'
    + 'Ada Lovelace, Member, IEEE, Alan Turing,\n\nGrace Hopper\n\nAbstract—SYNTHETIC abstract text.']
  const stored = buildDocument(pages(first), [], 'Synthetic Packet Scheduling in Molecular Relay Networks')
  expect(blocks(stored).slice(0, 4)).toEqual([
    ['para', 'IEEE TRANSACTIONS ON SYNTHETIC NETWORKS 1'],
    ['title', 'Synthetic Packet Scheduling in Molecular Relay Networks'],
    ['para', 'Ada Lovelace, Member, IEEE, Alan Turing, Grace Hopper'],
    ['para', 'Abstract—SYNTHETIC abstract text.'],
  ])
  // Without a matching stored title, Title Case lines are joined only when nothing is run into the first of them.
  const other = buildDocument(pages([first[0].replace('IEEE TRANSACTIONS ON SYNTHETIC NETWORKS 1\n', '')]), [], 'A Different Stored Title')
  expect(blocks(other)[0]).toEqual(['title', 'Synthetic Packet Scheduling in Molecular Relay Networks'])
  expect(blocks(buildDocument(pages(first), [], 'A Different Stored Title'))[0][0]).toBe('para')
})

test('section headings are separated from the text set in the same block, including capitals and drop capitals', () => {
  const doc = buildDocument(pages(['I. INTRODUCTION S\n\nYNTHETIC networks move molecules.\n\n'
    + 'II. SYSTEM MODEL\nIn this study, relays forward packets.\n'
    + 'IV. ROUTING PROTOCOLS FOR\nUWSNs\nThe network layer seeks routes.\n\n'
    + 'Node counts\n36. Crossbow\nMotes are cited here.\n\nREFERENCES\n\n[1] A. Author, “SYNTHETIC,” 2020.']), [], null)
  expect(doc.headings.map(h => h.text)).toEqual(['I. INTRODUCTION', 'II. SYSTEM MODEL', 'IV. ROUTING PROTOCOLS FOR UWSNs', 'REFERENCES'])
  expect(blocks(doc)[1]).toEqual(['para', 'SYNTHETIC networks move molecules.'])
  expect(blocks(doc).map(b => b[1])).toContain('Node counts 36. Crossbow Motes are cited here.')
})

test('a table cut across passages stays one table and the caption after it is its own paragraph', () => {
  const doc = buildDocument(pages([
    'Before the table.\n\n| Payload | Lifetime |\n| --- | --- |\n| 120 | 0.1 |',
    '| 60 | 0.2 |',
    'TABLE V: SYNTHETIC lifetime by payload (see Figure [4a](#page-6-2)).',
  ]), [], null)
  expect(blocks(doc)).toEqual([
    ['para', 'Before the table.'],
    ['table', '| Payload | Lifetime |\n| --- | --- |\n| 120 | 0.1 |\n| 60 | 0.2 |'],
    ['para', 'TABLE V: SYNTHETIC lifetime by payload (see Figure 4a).'],
  ])
  expect(doc.targets.get('table:V')).toBe(doc.pages[0].blocks[2].id)
})

test('biographies after the last reference get their own section in the paper’s language and heading case', () => {
  const doc = buildDocument(pages(['REFERENCES\n\n[1] A. Author, “SYNTHETIC relays,” in Proc. SYN, 2019.\n'
    + 'Ada Lovelace (ada@example.org) received the BS degree in 2009.\n\nShe works on SYNTHETIC relays.\n'
    + 'Alan Turing (M’05–SM’16) is a professor of SYNTHETIC networks.']), [], null)
  expect(blocks(doc)).toEqual([
    ['heading', 'REFERENCES'],
    ['para', '[1] A. Author, “SYNTHETIC relays,” in Proc. SYN, 2019.'],
    ['heading', 'BIOGRAPHIES'],
    ['bio', 'Ada Lovelace (ada@example.org) received the BS degree in 2009. She works on SYNTHETIC relays.'],
    ['bio', 'Alan Turing (M’05–SM’16) is a professor of SYNTHETIC networks.'],
  ])
  expect(doc.references.get('1')).toBe('[1] A. Author, “SYNTHETIC relays,” in Proc. SYN, 2019.')
})

test('figures, tables, equations and reference entries become jump targets', () => {
  const doc = buildDocument(pages(
    ['As Fig. 2 and Table II show [1], the rate follows Eq. (5).\n\nr = a + b (5)\n\nFig. 2. SYNTHETIC rate over time.'],
    ['TABLE II\n\nSYNTHETIC parameters\n\nREFERENCES\n\n[1] B. Author, “SYNTHETIC,” 2021.'],
  ), [{ page: 1, label: '2', width: 300, height: 200 }, { page: 2, label: '3', width: 300, height: 200 }], null)
  expect(blocks(doc)[2]).toEqual(['figure', 'Fig. 2. SYNTHETIC rate over time.'])
  expect(doc.targets.get('figure:2')).toBe('pdfx-fig-2')
  expect(doc.targets.get('eq:5')).toBe(doc.pages[0].blocks[1].id)
  expect(doc.targets.get('table:II')).toBe(doc.pages[1].blocks[0].id)
  expect(doc.targets.get('ref:1')).toBe(doc.pages[1].blocks[3].id)
  // A figure found on the page without a recognised caption still shows, at the end of its page.
  expect(blocks(doc, 1).at(-1)).toEqual(['figure', ''])
})

test('a citation anchor is found across line breaks, hyphenation and paragraph joins, and only on its own page', () => {
  const doc = buildDocument(pages(
    ['SYNTHETIC relays forward packets.\n\nIncreasing transmission power will re-\nduce the error rate on some links,', 'however, it raises interference on others.'],
    ['Increasing transmission power will reduce the error rate on some links.'],
  ), [], null)
  const marks = locateAnchors(doc, 1, ['Increasing transmission power will reduce the error rate on some links, however, it raises', 'not in this page'])
  expect(marks.located).toBe(1)
  const [id, ranges] = [...marks.blocks.entries()][0]
  expect(marks.first).toBe(id)
  const block = doc.pages[0].blocks.find(b => b.id === id)!
  expect(block.text.slice(ranges[0][0], ranges[0][1])).toBe('Increasing transmission power will re- duce the error rate on some links, however, it raises')
  expect(locateAnchors(doc, 2, ['however, it raises interference']).located).toBe(0)
})

test('a queue quote is marked only when the mark is exactly the quote: never in a heading, a table, part of a formula or part of a word', () => {
  const doc = buildDocument(pages([
    'II. SYSTEM MODEL\nIn this study, relays forward packets at the rate $r = a + b$ over the link.\n\n'
    + '| Payload | Lifetime |\n| --- | --- |\n| 120 | 0.1 |',
  ]), [], null)
  const exact = (text: string) => {
    const marks = locateAnchors(doc, 1, [text])
    expect(marks.located).toBe(1)  // each text is found; only whether its mark is exact differs
    return marksExactly(doc, marks, [text])
  }
  expect(exact('relays forward packets at the rate')).toBe(true)
  expect(exact('the rate $r = a + b$ over the link')).toBe(true)  // a whole formula inside the mark
  expect(exact('SYSTEM MODEL')).toBe(false)                     // a heading is marked whole
  expect(exact('Payload')).toBe(false)                           // so is a table
  expect(exact('rate $r = a')).toBe(false)                       // part of a formula would widen to all of it
  expect(exact('elays forward')).toBe(false)                     // part of a word would widen to the word
})
