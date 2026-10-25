export function readablePassageText(kind: string, text: string) {
  // Keep paragraph breaks, but undo the single line breaks introduced by PDF layout extraction.
  // Markdown table rows (D54) keep their own lines.
  return kind === 'pdf_page' ? text.replace(/(?<!\n)\n(?!\n)/g, (_, at: number) => text[at - 1] === '|' || text[at + 1] === '|' ? '\n' : ' ') : text
}

// Reading aids for extracted PDF text (D47): section headings stand out and author affiliation notes are folded away.
// Unnumbered headings are matched in title case and in capitals ("REFERENCES", "ACKNOWLEDGEMENT"), in English and Turkish.
const UNNUMBERED = ['Abstract', 'References', 'Acknowledgements', 'Acknowledgement', 'Acknowledgments', 'Acknowledgment', 'Appendix', 'Appendices',
  'Biographies', 'Author Biographies', 'Özet', 'Kaynaklar', 'Kaynakça', 'Teşekkür', 'Ekler', 'Biyografiler']
export const SECTION_HEADING = new RegExp(`^(?:(?:[IVXL]+|\\d+(?:\\.\\d+)*|[A-H])\\.?\\s+[A-Z][^.]{1,76}|${UNNUMBERED.flatMap(h => [h, h.toUpperCase(), h.toLocaleUpperCase('tr')]).join('|')})$`)
export const AUTHOR_NOTE = /\b(?:is|are) with the\b|\be-?mail:|^Corresponding author|^Manuscript received|^This work was (?:supported|funded)/i
