// A download's file name as Elicit writes it: `DEIXIS - <title> - <suffix>.<ext>`, the title as written (exports/text.py
// `download_name`). A colon becomes ' - ', the other characters a file system refuses become spaces; the title is cut at 120 characters.
// eslint-disable-next-line no-control-regex -- file names must not carry control characters
const tidy = (text: string) => text.replace(/\s*:\s*/g, ' - ').replace(/[\u0000-\u001f\u007f/\\*?"<>|]+/g, ' ').split(/\s+/).filter(Boolean).join(' ')

export function downloadName(title: string, suffixes: string[], extension: string, fallback = 'Research'): string {
  const parts = ['DEIXIS', tidy(title).slice(0, 120).trimEnd() || fallback, ...suffixes.map(tidy).filter(Boolean)]
  return extension ? `${parts.join(' - ')}.${extension}` : parts.join(' - ')
}
