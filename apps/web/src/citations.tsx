import { Fragment, type ReactNode } from 'react'
import type { Source } from './api'

export type CitationStyle = 'apa' | 'ieee' | 'mla' | 'chicago'

export const citationStyles: Record<CitationStyle, { label: string; detail: string }> = {
  apa: { label: 'APA 7', detail: 'Author, A. A., & Author, B. B. (Year). Title. Venue.' },
  ieee: { label: 'IEEE', detail: 'A. A. Author and B. B. Author, “Title,” Venue, Year.' },
  mla: { label: 'MLA 9', detail: 'Author, Given, and Given Author. “Title.” Venue, Year.' },
  chicago: { label: 'Chicago (author-date)', detail: 'Author, Given, and Given Author. Year. “Title.” Venue.' },
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

export function formatReference(style: CitationStyle, s: Source): ReactNode {
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
