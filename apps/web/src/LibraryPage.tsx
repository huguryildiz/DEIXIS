import { useEffect, useMemo, useState, type DragEvent } from 'react'
import {
  ArrowDown, ArrowLeft, ArrowUp, ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, FileText,
  FolderPlus, GripVertical, ListFilter, Rows2, Rows3, Search, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup,
  DropdownMenuItem, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  api, ApiError, assetUrl, type AccessLevel, type LibraryEntry, type LibraryResearch, type LibraryView,
  type LibraryWork, type LibraryWorkVersion,
} from './api'
import { PdfViewer } from './PdfViewer'
import { versionText } from './labels'
import { t, uiLocale } from './i18n'
import { useToast } from './Toast'
import './LibraryPage.css'

type SortKey = 'title' | 'year' | 'citations' | 'added'
type SortDir = 'asc' | 'desc'
type AccessFilter = AccessLevel | 'all'
type Density = 'comfortable' | 'compact'
type Grouping = 'project' | 'none'
type OpenPdf = { url: string; title: string; caption: string }
type Dragging = { workId: string; title: string; researchIds: string[] }

const DENSITY_KEY = 'deixis-library-density'
const GROUPING_KEY = 'deixis-library-grouping'
const PAGE_SIZE = 25
const GROUP_PAGE_SIZE = 10
const WORK_TYPE = 'application/x-deixis-work'

// Reading depth, not quality: what DEIXIS actually stored for this version.
const ACCESS_LABELS: Record<AccessLevel, string> = {
  pdf_available: 'PDF text',
  abstract: 'Abstract only',
  metadata: 'Metadata only',
}

const compareTitle = (a: LibraryEntry, b: LibraryEntry) => a.title.localeCompare(b.title, uiLocale())
const compareYear = (a: LibraryEntry, b: LibraryEntry) => (a.year ?? -1) - (b.year ?? -1)
const compareCitations = (a: LibraryEntry, b: LibraryEntry) => (a.cited_by_count ?? -1) - (b.cited_by_count ?? -1)
const compareAdded = (a: LibraryEntry, b: LibraryEntry) => a.newest_source_at.localeCompare(b.newest_source_at)

const authorsText = (authors: string[]) => (authors.length ? authors.join(', ') : t('Authors not stated'))
const yearText = (year: number | null) => (year ? String(year) : t('—'))
const dateText = (iso: string) => (iso ? new Date(iso).toLocaleDateString(uiLocale(), { dateStyle: 'medium' }) : t('—'))
const doiUrl = (doi: string | null, landing: string | null) => landing ?? (doi ? `https://doi.org/${doi}` : null)

function AccessTag({ level }: { level: AccessLevel }) {
  return <span className="library-access" data-level={level}>{t(ACCESS_LABELS[level])}</span>
}

const shortTitle = (title: string) => (title.length > 70 ? `${title.slice(0, 69)}…` : title)
const pageCount = (total: number, size: number) => Math.max(1, Math.ceil(total / size))

function Pager({ page, total, size, onPage, label }: { page: number; total: number; size: number; onPage: (page: number) => void; label: string }) {
  const pages = pageCount(total, size)
  if (pages <= 1) return null
  const first = page * size + 1
  const last = Math.min(total, (page + 1) * size)
  return <nav className="library-pager" aria-label={label}>
    <span>{t('{first}–{last} of {total}', { first, last, total: total.toLocaleString(uiLocale()) })}</span>
    <button type="button" onClick={() => onPage(page - 1)} disabled={page === 0} aria-label={t('Previous page')}><ChevronLeft size={14} aria-hidden /></button>
    <span aria-live="polite">{t('Page {page} of {pages}', { page: page + 1, pages })}</span>
    <button type="button" onClick={() => onPage(page + 1)} disabled={page >= pages - 1} aria-label={t('Next page')}><ChevronRight size={14} aria-hidden /></button>
  </nav>
}

export function LibraryPage({ onOpenResearch }: { onOpenResearch: (id: string) => void }) {
  const toast = useToast()
  const [entries, setEntries] = useState<LibraryEntry[] | null>(null)
  const [researches, setResearches] = useState<LibraryResearch[]>([])
  const [counts, setCounts] = useState<{ works: number; versions: number; researches: number } | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [access, setAccess] = useState<AccessFilter>('all')
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'title', dir: 'asc' })
  const [density, setDensity] = useState<Density>(() => {
    try { return localStorage.getItem(DENSITY_KEY) === 'compact' ? 'compact' : 'comfortable' } catch { return 'comfortable' }
  })
  const [grouping, setGrouping] = useState<Grouping>(() => {
    try { return localStorage.getItem(GROUPING_KEY) === 'none' ? 'none' : 'project' } catch { return 'project' }
  })
  const [page, setPage] = useState(0)
  const [groupPages, setGroupPages] = useState<Record<string, number>>({})
  const [folded, setFolded] = useState<Set<string>>(() => new Set())
  const [dragging, setDragging] = useState<Dragging | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [workVersion, setWorkVersion] = useState(0)
  const [work, setWork] = useState<LibraryWork | null>(null)
  const [workError, setWorkError] = useState('')
  const [pdf, setPdf] = useState<OpenPdf | null>(null)

  function show(view: LibraryView) {
    setEntries(view.entries)
    setResearches(view.researches)
    setCounts(view.counts)
  }
  function load() {
    api.library().then(show).catch((e: Error) => setError(e.message))
  }
  useEffect(load, [])

  useEffect(() => {
    if (!selected) return
    let current = true
    setWork(null)
    setWorkError('')
    api.libraryWork(selected)
      .then(result => { if (current) setWork(result) })
      .catch((e: Error) => { if (current) setWorkError(e.message) })
    return () => { current = false }
  }, [selected, workVersion])

  function chooseGrouping(next: Grouping) {
    setGrouping(next)
    resetPages()
    try { localStorage.setItem(GROUPING_KEY, next) } catch { /* the choice still applies for this tab */ }
  }

  // Adding a work makes one of its stored versions an included source of that research; the backend picks the version.
  async function addToResearch(workId: string, research: LibraryResearch) {
    const entry = entries?.find(e => e.work_id === workId)
    if (!entry || adding) return
    if (entry.researches.some(r => r.id === research.id)) {
      toast('warning', t('“{title}” is already a source of {project}.', { title: shortTitle(entry.title), project: shortTitle(research.title) }))
      return
    }
    setAdding(true)
    try {
      const result = await api.addLibrarySource(research.id, workId)
      show(result.library)
      if (selected === workId) setWorkVersion(v => v + 1)
      toast('success', t('Added to {project} as a source you included ({depth}).', {
        project: shortTitle(research.title), depth: t(ACCESS_LABELS[result.access_level]),
      }))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) { toast('warning', e.message); load() }
      else toast('error', t('Could not add the work: {message}', { message: (e as Error).message }))
    } finally {
      setAdding(false)
    }
  }

  function startDrag(event: DragEvent, entry: LibraryEntry) {
    event.dataTransfer.effectAllowed = 'copy'
    event.dataTransfer.setData(WORK_TYPE, entry.work_id)
    event.dataTransfer.setData('text/plain', entry.doi ? `${entry.title} (doi:${entry.doi})` : entry.title)
    setDragging({ workId: entry.work_id, title: entry.title, researchIds: entry.researches.map(r => r.id) })
  }
  function endDrag() {
    setDragging(null)
    setDropTarget(null)
  }
  // Drop handlers for one research: a work that is already its source is not a valid drop there.
  const dropProps = (research: LibraryResearch) => ({
    onDragOver: (event: DragEvent) => {
      if (!dragging || dragging.researchIds.includes(research.id)) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
      if (dropTarget !== research.id) setDropTarget(research.id)
    },
    onDragLeave: (event: DragEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropTarget(current => current === research.id ? null : current)
    },
    onDrop: (event: DragEvent) => {
      event.preventDefault()
      const workId = event.dataTransfer.getData(WORK_TYPE) || dragging?.workId
      endDrag()
      if (workId) void addToResearch(workId, research)
    },
    'data-drop': !dragging ? undefined : dragging.researchIds.includes(research.id) ? 'present' : dropTarget === research.id ? 'over' : 'ready',
  })

  function chooseDensity(next: Density) {
    setDensity(next)
    try { localStorage.setItem(DENSITY_KEY, next) } catch { /* the choice still applies for this tab */ }
  }

  const filtered = useMemo(() => {
    const items = entries ?? []
    const q = query.trim().toLowerCase()
    const list = items.filter(entry => {
      if (access !== 'all' && entry.access_level !== access) return false
      if (!q) return true
      return [entry.title, authorsText(entry.authors), entry.venue ?? '', entry.doi ?? '', ...entry.researches.map(r => r.title)]
        .join('\n').toLowerCase().includes(q)
    })
    const dir = sort.dir === 'asc' ? 1 : -1
    const compare = sort.key === 'title' ? compareTitle : sort.key === 'year' ? compareYear
      : sort.key === 'citations' ? compareCitations : compareAdded
    return [...list].sort((a, b) => compare(a, b) * dir)
  }, [entries, query, access, sort])

  // A work used by several researches appears in each of their groups.
  const groups = useMemo(() => researches.map(research => ({
    research, entries: filtered.filter(entry => entry.researches.some(r => r.id === research.id)),
  })), [researches, filtered])
  const narrowed = query.trim() !== '' || access !== 'all'
  const pages = pageCount(filtered.length, PAGE_SIZE)
  const currentPage = Math.min(page, pages - 1)

  // Any change to what the list contains or how it is ordered starts again from the first page.
  function resetPages() {
    setPage(0)
    setGroupPages({})
  }

  function toggleFold(id: string) {
    setFolded(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function cycleSort(key: SortKey) {
    resetPages()
    setSort(current => current.key === key
      ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: key === 'title' ? 'asc' : 'desc' })
  }
  const sortIcon = (key: SortKey) => sort.key !== key ? <ArrowUpDown size={12} aria-hidden />
    : sort.dir === 'asc' ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden />
  const ariaSort = (key: SortKey) => sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
  const sortable = (key: SortKey, label: string, hint: string, className?: string) =>
    <th className={className} aria-sort={ariaSort(key)} scope="col">
      <button type="button" onClick={() => cycleSort(key)} aria-label={t(hint)}>{t(label)}{sortIcon(key)}</button>
    </th>

  const renderRow = (entry: LibraryEntry, key: string) => <tr key={key} className={[entry.work_id === selected ? 'is-selected' : '', dragging?.workId === entry.work_id ? 'is-dragging' : ''].join(' ')}
              draggable onDragStart={event => startDrag(event, entry)} onDragEnd={endDrag}
              onClick={() => setSelected(entry.work_id)}>
              <td className="library-col-paper">
                <GripVertical size={13} className="library-grip" aria-hidden />
                <button type="button" className="library-title" onClick={() => setSelected(entry.work_id)}
                  aria-expanded={entry.work_id === selected} title={entry.title}>{entry.title}</button>
                {entry.versions.length > 1 && <span className="library-version-note">{t('{n} versions', { n: entry.versions.length })}</span>}
              </td>
              <td className="library-col-authors" title={authorsText(entry.authors)}>{authorsText(entry.authors)}</td>
              <td className="library-col-venue" title={entry.venue ?? undefined}>{entry.venue ?? t('—')}</td>
              <td className="library-col-access"><AccessTag level={entry.access_level} /></td>
              <td className="library-col-year">{yearText(entry.year)}</td>
              <td className="library-col-citations">{entry.cited_by_count !== null ? entry.cited_by_count.toLocaleString(uiLocale()) : t('—')}</td>
              <td className="library-col-projects" title={entry.researches.map(r => r.title).join(' · ')}>
                {entry.researches.length === 1 ? entry.researches[0].title : t('{n} projects', { n: entry.researches.length })}
              </td>
              <td className="library-col-added">{dateText(entry.newest_source_at)}</td>
            </tr>

  if (pdf) return <section className="collection library-page library-reader">
    <button type="button" className="back-button" onClick={() => setPdf(null)}><ArrowLeft size={14} aria-hidden />{t('Back to the Library')}</button>
    <h2>{pdf.title}</h2>
    <p className="library-reader-caption">{pdf.caption}</p>
    <div className="library-reader-frame"><PdfViewer url={pdf.url} title={pdf.title} /></div>
  </section>

  return <section className="collection library-page">
    <div className="section-label">{t('LIBRARY')}</div>
    <h1>{t('Library')}</h1>
    <p>{t('Every work saved across your research, with its versions and the projects that use it. Citation counts come from OpenAlex and are metadata, not a quality judgment.')}</p>

    <div className="library-toolbar">
      <div className="library-search" role="search">
        <Search size={15} aria-hidden />
        <input type="search" value={query} onChange={event => { setQuery(event.target.value); resetPages() }}
          placeholder={t('Search by title, author, venue, DOI or project')} aria-label={t('Search the library')} />
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger className="library-tool" aria-label={t('Filter by reading depth')}>
          <ListFilter size={14} aria-hidden />{t('Reading depth')}
          {access !== 'all' && <span className="library-tool-value">{t(ACCESS_LABELS[access])}</span>}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-auto">
          <div className="library-menu-label">{t('Reading depth')}</div>
          <DropdownMenuRadioGroup value={access} onValueChange={value => { setAccess(value as AccessFilter); resetPages() }}>
            <DropdownMenuRadioItem value="all">{t('Any depth')}</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="pdf_available">{t('PDF text')}</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="abstract">{t('Abstract only')}</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="metadata">{t('Metadata only')}</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
          <DropdownMenuSeparator />
          <p className="library-menu-note">{t('What DEIXIS stored for the work, not a quality judgment.')}</p>
        </DropdownMenuContent>
      </DropdownMenu>
      <div className="library-density" role="group" aria-label={t('Row density')}>
        <button type="button" aria-pressed={density === 'comfortable'} onClick={() => chooseDensity('comfortable')}
          aria-label={t('Comfortable rows')} title={t('Comfortable rows')}><Rows2 size={14} aria-hidden /></button>
        <button type="button" aria-pressed={density === 'compact'} onClick={() => chooseDensity('compact')}
          aria-label={t('Compact rows')} title={t('Compact rows')}><Rows3 size={14} aria-hidden /></button>
      </div>
      <div className="library-density" role="group" aria-label={t('Group works')}>
        <button type="button" className="library-group-choice" aria-pressed={grouping === 'project'} onClick={() => chooseGrouping('project')}>{t('By project')}</button>
        <button type="button" className="library-group-choice" aria-pressed={grouping === 'none'} onClick={() => chooseGrouping('none')}>{t('All works')}</button>
      </div>
      {counts && <p className="library-counts">
        <span>{t('{shown} of {total} works', { shown: filtered.length.toLocaleString(uiLocale()), total: counts.works.toLocaleString(uiLocale()) })}</span>
        <span aria-hidden="true">·</span>
        <span>{t('{n} versions', { n: counts.versions.toLocaleString(uiLocale()) })}</span>
        <span aria-hidden="true">·</span>
        <span>{t('{n} projects', { n: counts.researches.toLocaleString(uiLocale()) })}</span>
      </p>}
    </div>

    {error && <div className="legacy-boundary" role="alert">{t('Could not load the Library: {message}', { message: error })} <Button variant="outline" onClick={() => { setError(''); load() }}>{t('Retry')}</Button></div>}
    {!error && entries === null && <p className="library-status" role="status">{t('Loading Library…')}</p>}
    {!error && entries !== null && !filtered.length && <p className="library-status">{query || access !== 'all' ? t('No work matches the current search and filter.') : t('No works yet. Sources you save in a research will appear here.')}</p>}

    {dragging && grouping === 'none' && <div className="library-dock" role="region" aria-label={t('Projects to drop on')}>
      <span className="library-dock-label">{t('Drop on a project to include “{title}” as a source', { title: dragging.title })}</span>
      <div className="library-dock-targets">
        {researches.map(research => <div key={research.id} className="library-dock-target" title={research.title} {...dropProps(research)}>{research.title}</div>)}
      </div>
    </div>}

    {!error && filtered.length > 0 && <div className={`library-layout ${selected ? 'has-panel' : ''}`}>
      <div className="library-table-wrap" data-density={density}>
        <table className="library-table">
          <thead>
            <tr>
              {sortable('title', 'Paper', 'Sort by paper title', 'library-col-paper')}
              <th scope="col" className="library-col-authors">{t('Authors')}</th>
              <th scope="col" className="library-col-venue">{t('Venue')}</th>
              <th scope="col" className="library-col-access">{t('Reading depth')}</th>
              {sortable('year', 'Year', 'Sort by year', 'library-col-year')}
              {sortable('citations', 'Citations', 'Sort by citation count', 'library-col-citations')}
              <th scope="col" className="library-col-projects">{t('Projects')}</th>
              {sortable('added', 'Added', 'Sort by the date the work was saved', 'library-col-added')}
            </tr>
          </thead>
          {grouping === 'none' && <tbody>
            {filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(entry => renderRow(entry, entry.work_id))}
          </tbody>}
          {grouping === 'project' && groups.map(({ research, entries: rows }) => {
            // An empty group stays visible while nothing narrows the list, and while a drag needs somewhere to land.
            if (!rows.length && narrowed && !dragging) return null
            const isFolded = folded.has(research.id)
            const groupPage = Math.min(groupPages[research.id] ?? 0, pageCount(rows.length, GROUP_PAGE_SIZE) - 1)
            return <tbody key={research.id} className="library-group" {...dropProps(research)}>
              <tr className="library-group-row">
                <th colSpan={8} scope="rowgroup">
                  <div className="library-group-head">
                    <button type="button" className="library-group-toggle" onClick={() => toggleFold(research.id)}
                      aria-expanded={!isFolded} title={research.title}>
                      {isFolded ? <ChevronRight size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
                      <span className="library-group-title">{research.title}</span>
                      <span className="library-group-count">{rows.length.toLocaleString(uiLocale())}</span>
                    </button>
                    {dragging && !dragging.researchIds.includes(research.id) && <span className="library-drop-hint">{t('Drop to include as a source')}</span>}
                    {dragging?.researchIds.includes(research.id) && <span className="library-drop-hint">{t('Already a source')}</span>}
                    <button type="button" className="library-group-open" onClick={() => onOpenResearch(research.id)}>
                      {t('Open research')}<ChevronRight size={13} aria-hidden />
                    </button>
                  </div>
                </th>
              </tr>
              {!isFolded && !rows.length && <tr className="library-group-empty"><td colSpan={8}>{narrowed ? t('No work in this project matches the current search and filter.') : t('No sources yet. Drag a work here to include it.')}</td></tr>}
              {!isFolded && rows.slice(groupPage * GROUP_PAGE_SIZE, (groupPage + 1) * GROUP_PAGE_SIZE).map(entry => renderRow(entry, `${research.id}:${entry.work_id}`))}
              {!isFolded && rows.length > GROUP_PAGE_SIZE && <tr className="library-group-pager"><td colSpan={8}>
                <Pager page={groupPage} total={rows.length} size={GROUP_PAGE_SIZE} label={t('Pages of {project}', { project: research.title })}
                  onPage={next => setGroupPages(current => ({ ...current, [research.id]: next }))} />
              </td></tr>}
            </tbody>
          })}
        </table>
        {grouping === 'none' && <Pager page={currentPage} total={filtered.length} size={PAGE_SIZE} onPage={setPage} label={t('Library pages')} />}
      </div>

      {selected && <WorkPanel work={work} error={workError} onClose={() => setSelected(null)}
        onOpenResearch={onOpenResearch} onOpenPdf={setPdf} researches={researches} adding={adding}
        onAdd={research => void addToResearch(selected, research)} />}
    </div>}
  </section>
}

function versionCaption(version: LibraryWorkVersion) {
  const parts = [versionText(version.version_label), version.year ? String(version.year) : null, version.venue]
  return parts.filter(Boolean).join(' · ')
}

function WorkPanel({ work, error, onClose, onOpenResearch, onOpenPdf, researches, adding, onAdd }: {
  work: LibraryWork | null; error: string; onClose: () => void
  onOpenResearch: (id: string) => void; onOpenPdf: (pdf: OpenPdf) => void
  researches: LibraryResearch[]; adding: boolean; onAdd: (research: LibraryResearch) => void
}) {
  const addable = work ? researches.filter(research => !work.researches.some(r => r.id === research.id)) : []
  const abstractVersion = work?.versions.find(version => version.abstract) ?? null
  const link = work ? doiUrl(work.doi, work.landing_url) : null

  return <aside className="library-panel" aria-label={t('Work details')}>
    <div className="library-panel-head">
      <strong>{t('Work details')}</strong>
      <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label={t('Close work details')}><X size={16} /></Button>
    </div>
    <div className="library-panel-body">
      {error && <div className="legacy-boundary" role="alert">{t('Could not load this work: {message}', { message: error })}</div>}
      {!error && !work && <p className="library-status" role="status">{t('Loading work…')}</p>}
      {work && <>
        <h2>{work.title}</h2>
        <p className="library-panel-authors">{authorsText(work.authors)}</p>
        <p className="library-panel-meta">{[work.venue, work.year ? String(work.year) : null].filter(Boolean).join(' · ') || t('—')}</p>
        {link && <a className="library-panel-link" href={link} target="_blank" rel="noopener noreferrer">
          {work.doi ? `DOI: ${work.doi}` : t('Open the source page')}<ExternalLink size={12} aria-hidden />
        </a>}
        {work.cited_by_count !== null && <p className="library-panel-note">{t('Cited by {count} (OpenAlex metadata)', { count: work.cited_by_count.toLocaleString(uiLocale()) })}</p>}

        <h3>{t('Versions')}</h3>
        <ul className="library-version-list">
          {work.versions.map(version => <li key={version.source_version_id}>
            <div className="library-version-head">
              <strong>{versionCaption(version)}</strong>
              <AccessTag level={version.access_level} />
            </div>
            {version.asset && <p className="library-version-file">{version.asset.original_filename ?? t('PDF')}
              {version.asset.page_count ? ` · ${t('{n} pages', { n: version.asset.page_count })}` : ''}</p>}
            {version.asset && version.research_id && <Button variant="outline" size="sm" className="library-version-open"
              onClick={() => onOpenPdf({
                url: assetUrl(version.research_id as string, (version.asset as { id: string }).id),
                title: work.title, caption: versionCaption(version),
              })}><FileText size={14} />{t('Read the PDF')}</Button>}
            {!version.asset && <p className="library-version-file">{t('No PDF is stored for this version.')}</p>}
          </li>)}
        </ul>

        <h3>{t('Abstract')}</h3>
        {abstractVersion
          ? <>
            <p className="library-abstract">{abstractVersion.abstract}</p>
            <p className="library-panel-note">{t('From {version}{origin}', {
              version: versionCaption(abstractVersion),
              origin: abstractVersion.abstract_origin === 'provider_openalex_inverted_index' ? ` · ${t('rebuilt from the OpenAlex index')}` : '',
            })}</p>
          </>
          : <p className="library-panel-note">{t('No abstract is stored for any version of this work.')}</p>}

        <h3>{t('Projects')}</h3>
        <div className="library-panel-projects">
          {work.researches.map(research => <button key={research.id} type="button" onClick={() => onOpenResearch(research.id)}
            title={research.title}>{research.title}<ChevronRight size={13} aria-hidden /></button>)}
        </div>
        {addable.length > 0 && <DropdownMenu>
          <DropdownMenuTrigger className="library-tool library-add-trigger" disabled={adding}>
            <FolderPlus size={14} aria-hidden />{t('Add to a project')}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="library-add-menu">
            {addable.map(research => <DropdownMenuItem key={research.id} onClick={() => onAdd(research)}>{research.title}</DropdownMenuItem>)}
          </DropdownMenuContent>
        </DropdownMenu>}
        {addable.length > 0 && <p className="library-panel-note">{t('Adding includes one stored version as a source you chose; you can exclude it in that research.')}</p>}
      </>}
    </div>
  </aside>
}
