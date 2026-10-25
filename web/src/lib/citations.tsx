import { Fragment, useSyncExternalStore, type ReactNode } from 'react'
import type { Source } from './api'

export type CitationStyle = 'apa' | 'ieee' | 'mla' | 'chicago'

export const citationStyles: Record<CitationStyle, { label: string }> = {
  apa: { label: 'APA 7' },
  ieee: { label: 'IEEE' },
  mla: { label: 'MLA 9' },
  chicago: { label: 'Chicago (author-date)' },
}

// The fields a reference is written from. The style menu previews each style on the report's first cited source with
// authors (the styles differ mostly in how they write names), or on this real article when there is none.
export type ReferenceFields = Pick<Source, 'title' | 'authors' | 'year' | 'venue' | 'doi' | 'landing_url' | 'publication_type'>
export const SAMPLE_REFERENCE: ReferenceFields = {
  title: 'Molecular structure of nucleic acids: A structure for deoxyribose nucleic acid', authors: ['James D. Watson', 'Francis H. C. Crick'],
  year: 1953, venue: 'Nature', doi: null, landing_url: null, publication_type: 'article',
}

// The citation style chosen on a report: one value for the whole page, kept across reloads. The report panel, the
// thread's chips, the Export menus and the table read it through this store, so an export made right after a change
// already uses the new style (a value read from storage at an earlier render would not).
const STYLE_KEY = 'deixis-citation-style'
const readStyle = (): CitationStyle => {
  try { const saved = localStorage.getItem(STYLE_KEY); return saved && saved in citationStyles ? saved as CitationStyle : 'apa' } catch { return 'apa' }
}
let currentStyle: CitationStyle | null = null
const styleListeners = new Set<() => void>()
export function citationStyle(): CitationStyle { return (currentStyle ??= readStyle()) }
function setCitationStyle(next: CitationStyle) {
  currentStyle = next
  try { localStorage.setItem(STYLE_KEY, next) } catch { /* the choice still applies for this tab */ }
  styleListeners.forEach(listener => listener())
}
const subscribeStyle = (listener: () => void) => { styleListeners.add(listener); return () => { styleListeners.delete(listener) } }
export function useCitationStyle(): [CitationStyle, (next: CitationStyle) => void] {
  return [useSyncExternalStore(subscribeStyle, citationStyle), setCitationStyle]
}

type Name = { family: string; given: string[] }

// Provider author names are single display strings ("Christodoulos A. Floudas"). The last word is taken as the
// family name, so particles ("van der") and suffixes ("Jr.") are not recognised.
const parse = (full: string): Name => { const words = full.trim().split(/\s+/); return { family: words.pop() ?? '', given: words } }
const initials = (n: Name) => n.given.map(g => g.split('-').map(p => `${p.charAt(0).toUpperCase()}.`).join('-')).join(' ')
const inverted = (n: Name) => (n.given.length ? `${n.family}, ${n.given.join(' ')}` : n.family)
const natural = (n: Name) => [...n.given, n.family].join(' ')
const end = (text: string, mark: string) => (/[.?!]$/.test(text) ? text : text + mark)
const series = (items: string[], and: string) => (items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')}, ${and} ${items.at(-1)}`)
const commas = (parts: ReactNode[]) => parts.map((part, i) => <Fragment key={i}>{i > 0 && ', '}{part}</Fragment>)
const italicTitle = (title: string) => <><em>{title}</em>{/[.?!]$/.test(title) ? '' : '.'}</>

export function formatReference(style: CitationStyle, s: ReferenceFields): ReactNode {
  const names = s.authors.map(parse)
  const book = s.publication_type === 'book'
  const link = s.doi ? `https://doi.org/${s.doi}` : s.landing_url
  const venue = s.venue && (book ? s.venue : <em>{s.venue}</em>)
  switch (style) {
    case 'apa': {
      const people = names.map(n => (n.given.length ? `${n.family}, ${initials(n)}` : n.family))
      const authors = people.length > 20 ? `${people.slice(0, 19).join(', ')}, . . . ${people.at(-1)}` : series(people, '&')
      const date = `(${s.year ?? 'n.d.'}).`
      const title = book ? italicTitle(s.title) : end(s.title, '.')
      return <>{authors ? <>{authors} {date} {title}</> : <>{title} {date}</>}{venue && <> {venue}.</>}{link && <> {link}</>}</>
    }
    case 'ieee': {
      const people = names.map(n => [initials(n), n.family].filter(Boolean).join(' '))
      const authors = people.length > 6 ? `${people[0]} et al.` : people.length === 2 ? people.join(' and ') : series(people, 'and')
      const tail = [venue, s.year, s.doi && `doi: ${s.doi}`].filter(Boolean)
      const title = book ? italicTitle(s.title) : `“${end(s.title, tail.length ? ',' : '.')}”`
      return <>{authors && `${authors}, `}{title}{tail.length > 0 && <> {commas(tail)}.</>}</>
    }
    case 'mla': {
      const authors = !names.length ? '' : names.length === 1 ? inverted(names[0]) : names.length === 2 ? `${inverted(names[0])}, and ${natural(names[1])}` : `${inverted(names[0])}, et al.`
      const tail = [venue, s.year, link].filter(Boolean)
      const title = book ? italicTitle(s.title) : `“${end(s.title, '.')}”`
      return <>{authors && `${end(authors, '.')} `}{title}{tail.length > 0 && <> {commas(tail)}.</>}</>
    }
    case 'chicago': {
      const people = names.map((n, i) => (i === 0 ? inverted(n) : natural(n)))
      const authors = people.length > 10 ? `${people.slice(0, 7).join(', ')}, et al.` : series(people, 'and')
      const date = `${s.year ?? 'n.d.'}.`
      const title = book ? italicTitle(s.title) : `“${end(s.title, '.')}”`
      return <>{authors ? <>{end(authors, '.')} {date} {title}</> : <>{title} {date}</>}{venue && <> {venue}.</>}{link && <> {link}.</>}</>
    }
  }
}

// A source cited in the text of an author-date style, without the parentheses: APA "Zeng et al., 2022", Chicago
// "Zeng et al. 2022", MLA "Zeng et al.". null in IEEE (cited by number) and for a source without authors.
export function inTextCitation(style: CitationStyle, s: Pick<ReferenceFields, 'authors' | 'year'>, locator?: string): string | null {
  if (style === 'ieee' || !s.authors.length) return null
  const families = s.authors.map(a => parse(a).family)
  const who = families.length === 1 ? families[0]
    : families.length === 2 ? `${families[0]} ${style === 'apa' ? '&' : 'and'} ${families[1]}`
    : style === 'chicago' && families.length === 3 ? `${families[0]}, ${families[1]}, and ${families[2]}`
    : `${families[0]} et al.`
  const year = s.year ?? 'n.d.'
  const head = style === 'apa' ? `${who}, ${year}` : style === 'chicago' ? `${who} ${year}` : who
  return locator ? `${head}, ${locator}` : head
}

// Plain-text companion for report copy/download. Keep it beside the visual formatter so exported
// references follow the citation style selected in the report drawer.
export function formatReferenceText(style: CitationStyle, s: Source): string {
  const names = s.authors.map(parse)
  const book = s.publication_type === 'book'
  const link = s.doi ? `https://doi.org/${s.doi}` : s.landing_url
  switch (style) {
    case 'apa': {
      const people = names.map(n => (n.given.length ? `${n.family}, ${initials(n)}` : n.family))
      const authors = people.length > 20 ? `${people.slice(0, 19).join(', ')}, . . . ${people.at(-1)}` : series(people, '&')
      const date = `(${s.year ?? 'n.d.'}).`
      const title = end(s.title, '.')
      return [authors ? `${authors} ${date} ${title}` : `${title} ${date}`, s.venue ? end(s.venue, '.') : '', link ?? ''].filter(Boolean).join(' ')
    }
    case 'ieee': {
      const people = names.map(n => [initials(n), n.family].filter(Boolean).join(' '))
      const authors = people.length > 6 ? `${people[0]} et al.` : people.length === 2 ? people.join(' and ') : series(people, 'and')
      const title = book ? end(s.title, '.') : `“${end(s.title, s.venue || s.year || s.doi ? ',' : '.')}”`
      const tail = [s.venue, s.year?.toString(), s.doi && `doi: ${s.doi}`].filter(Boolean).join(', ')
      return `${authors ? `${authors}, ` : ''}${title}${tail ? ` ${end(tail, '.')}` : ''}`
    }
    case 'mla': {
      const authors = !names.length ? '' : names.length === 1 ? inverted(names[0]) : names.length === 2 ? `${inverted(names[0])}, and ${natural(names[1])}` : `${inverted(names[0])}, et al.`
      const title = book ? end(s.title, '.') : `“${end(s.title, '.')}”`
      return [authors ? end(authors, '.') : '', title, s.venue ? end(s.venue, ',') : '', s.year?.toString() ?? '', link ?? ''].filter(Boolean).join(' ')
    }
    case 'chicago': {
      const people = names.map((n, i) => (i === 0 ? inverted(n) : natural(n)))
      const authors = people.length > 10 ? `${people.slice(0, 7).join(', ')}, et al.` : series(people, 'and')
      const title = book ? end(s.title, '.') : `“${end(s.title, '.')}”`
      return [authors ? end(authors, '.') : '', `${s.year ?? 'n.d.'}.`, title, s.venue ? end(s.venue, '.') : '', link ? end(link, '.') : ''].filter(Boolean).join(' ')
    }
  }
}

// One source as a BibTeX entry for "Copy as BibTeX" (Source details, P14). Only stored fields are written; a field the
// record does not hold is left out. The key is the source's key (D59), else a plain author-year key.
export function formatBibtex(s: Source): string {
  const brace = (value: string) => value.replace(/[{}\\]/g, '')
  const key = (s.source_key ?? `${parse(s.authors[0] ?? 'source').family}${s.year ?? ''}`).replace(/[^A-Za-z0-9_:-]/g, '') || 'source'
  const kind = s.publication_type === 'book' ? 'book' : s.venue ? 'article' : 'misc'
  const fields: [string, string | null | undefined][] = [
    ['title', s.title], ['author', s.authors.length ? s.authors.join(' and ') : null],
    [kind === 'book' ? 'publisher' : 'journal', s.venue], ['year', s.year?.toString()], ['volume', s.volume], ['number', s.issue],
    ['pages', s.pages], ['doi', s.doi], ['url', s.doi ? null : s.landing_url],
  ]
  return `@${kind}{${key},\n${fields.filter(([, v]) => v).map(([k, v]) => `  ${k} = {${brace(v!)}}`).join(',\n')}\n}\n`
}
