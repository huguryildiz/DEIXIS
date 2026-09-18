import { useEffect, useMemo, useState, type DragEvent } from 'react'
import {
  ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight,
  Ellipsis, Folder, GripVertical, Info, ListFilter, Rows2, Rows3, Search, Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup,
  DropdownMenuItem, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  api, ApiError, type AccessLevel, type LibraryEntry, type LibraryResearch, type LibraryView,
  type LibraryWork,
} from './api'
import { ConfirmDialog } from './ConfirmDialog'
import { SourceKey } from './SourceKey'
import { PassageSheet } from './PassageSheet'
import { versionText, versionTones } from './labels'
import { t, uiLocale } from './i18n'
import { useToast } from './Toast'
import './LibraryPage.css'
import { Notice } from './Notice'

type SortKey = 'title' | 'year' | 'citations' | 'added'
type SortDir = 'asc' | 'desc'
type AccessFilter = AccessLevel | 'all'
type Density = 'comfortable' | 'compact'
type Grouping = 'project' | 'none'
type Dragging = { workId: string; title: string; researchIds: string[] }
// Removing works takes them out of one project, or out of every project that uses them in the all-works list (D50);
// research = null is that library-wide scope. Picking in another project starts the selection again there.
type Picked = { research: string | null; works: Set<string> }
type Pending = { research: string | null; works: string[] }

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
const ACCESS_PILLS: Record<AccessLevel, string> = {
  pdf_available: 'is-text',
  abstract: 'is-abstract',
  metadata: 'is-unstated',
}

function AccessTag({ level }: { level: AccessLevel }) {
  return <span className={`ref-pill ${ACCESS_PILLS[level]}`}>{t(ACCESS_LABELS[level])}</span>
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

const NO_PICKS: ReadonlySet<string> = new Set<string>()

// `researchKey` changes when a research is trashed, restored or deleted elsewhere in the app, so the
// Library reloads instead of keeping rows of a research that is no longer in the workspace.
export function LibraryPage({ dark, researchKey, onChanged, onOpenResearch }: { dark: boolean; researchKey: string; onChanged: () => void; onOpenResearch: (id: string) => void }) {
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
  const [picked, setPicked] = useState<Picked>({ research: null, works: new Set() })
  const [pending, setPending] = useState<Pending | null>(null)
  const [removing, setRemoving] = useState(false)

  // The source sheet opens the PDF of a version a research still holds, else that version's abstract (D50).
  const sheet = sheetTarget(work)

  // A metadata-only work has no stored text to inspect, so the row says so instead of opening an empty sheet.
  function openWork(entry: LibraryEntry) {
    if (entry.access_level === 'metadata') {
      toast('warning', t('No abstract or PDF text is stored for “{title}”.', { title: shortTitle(entry.title) }))
      return
    }
    setSelected(entry.work_id)
  }

  function show(view: LibraryView) {
    setEntries(view.entries)
    setResearches(view.researches)
    setCounts(view.counts)
    // A work whose only research left the workspace is gone; its open panel would show a stale record.
    setSelected(current => (current && !view.entries.some(entry => entry.work_id === current) ? null : current))
  }
  function load() {
    api.library().then(show).catch((e: Error) => setError(e.message))
  }
  useEffect(load, [researchKey])

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

  // Escape clears the selection, as the bar's key hint promises. An open confirmation keeps the key for itself.
  useEffect(() => {
    if (!picked.works.size || pending) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) setPicked({ research: null, works: new Set() })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [picked.works.size, pending])

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

  const picksIn = (researchId: string | null) => (picked.research === researchId ? picked.works : NO_PICKS)
  const clearPicks = () => setPicked({ research: null, works: new Set() })

  function togglePick(workId: string, researchId: string | null) {
    setPicked(current => {
      const works = current.research === researchId ? new Set(current.works) : new Set<string>()
      if (works.has(workId)) works.delete(workId); else works.add(workId)
      return { research: researchId, works }
    })
  }
  // The header box picks every work of the project, or clears them when they are all picked already.
  function togglePickAll(researchId: string | null, workIds: string[]) {
    setPicked(current => {
      const all = current.research === researchId && workIds.every(id => current.works.has(id))
      return { research: researchId, works: new Set(all ? [] : workIds) }
    })
  }

  const projectTitle = (researchId: string) => researches.find(r => r.id === researchId)?.title ?? t('this project')

  // The one way to delete a project, wherever it is shown: the research goes to the Trash and every view drops it (D50).
  function trashProject(research: LibraryResearch) {
    // onChanged refreshes the research list the rest of the app renders, so the sidebar drops the row at once
    // instead of on its next poll.
    api.moveToTrash(research.id).then(() => {
      load()
      onChanged()
      toast('success', t('Moved to Trash.'), { label: t('Undo'), run: () => {
        api.restore(research.id).then(() => { load(); onChanged(); toast('success', t('Research restored.')) },
          (e: Error) => toast('error', t('Could not restore research: {message}', { message: e.message })))
      } })
    }, (e: Error) => toast('error', t('Could not move to Trash: {message}', { message: e.message })))
  }

  // Every stored version of the work leaves the research's source list; nothing about the record or its files changes,
  // so the notification's Undo, like the Trash page, puts it back (D50).
  async function removeWorks({ research, works }: Pending) {
    const targets = new Map<string, string[]>()
    for (const workId of works) {
      const entry = entries?.find(e => e.work_id === workId)
      if (!entry) continue
      const svids = entry.versions.map(v => v.source_version_id)
      for (const rid of research ? [research] : entry.researches.map(r => r.id)) {
        targets.set(rid, [...(targets.get(rid) ?? []), ...svids])
      }
    }
    setRemoving(true)
    const undo: { research: string; svids: string[] }[] = []
    try {
      for (const [rid, svids] of targets) {
        const result = await api.removeSources(rid, svids)
        if (result.changed_source_version_ids.length) undo.push({ research: rid, svids: result.changed_source_version_ids })
      }
      setPicked({ research: null, works: new Set() })
      setPending(null)
      if (selected && works.includes(selected)) setSelected(null)
      load()
      const restore = () => Promise.all(undo.map(u => api.restoreSources(u.research, u.svids)))
        .then(load)
        .catch((e: Error) => toast('error', t('Could not put it back: {message}', { message: e.message })))
      const one = works.length === 1 ? shortTitle(entries?.find(e => e.work_id === works[0])?.title ?? '') : null
      toast('success', research
        ? (one ? t('“{title}” removed from {project}.', { title: one, project: shortTitle(projectTitle(research)) })
          : t('{n} works removed from {project}.', { n: works.length, project: shortTitle(projectTitle(research)) }))
        : (one ? t('“{title}” removed from every project that used it.', { title: one })
          : t('{n} works removed from every project that used them.', { n: works.length })),
        undo.length ? { label: t('Undo'), run: () => void restore() } : undefined)
    } catch (e) {
      toast('error', t('Could not remove: {message}', { message: (e as Error).message }))
    } finally {
      setRemoving(false)
    }
  }

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

  // A project's header box picks every work in it while only one page of rows is rendered, so the count in the bar
  // can be far larger than what is on screen. This is how many of the picked works the user cannot currently see.
  const offPagePicks = useMemo(() => {
    if (!picked.works.size) return 0
    let shown: string[] = []
    if (picked.research === null) {
      shown = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(entry => entry.work_id)
    } else if (!folded.has(picked.research)) {
      const rows = groups.find(group => group.research.id === picked.research)?.entries ?? []
      const groupPage = Math.min(groupPages[picked.research] ?? 0, pageCount(rows.length, GROUP_PAGE_SIZE) - 1)
      shown = rows.slice(groupPage * GROUP_PAGE_SIZE, (groupPage + 1) * GROUP_PAGE_SIZE).map(entry => entry.work_id)
    }
    const visible = new Set(shown)
    return [...picked.works].filter(workId => !visible.has(workId)).length
  }, [picked, filtered, currentPage, groups, groupPages, folded])

  // Any change to what the list contains or how it is ordered starts again from the first page.
  function resetPages() {
    setPage(0)
    setGroupPages({})
    setPicked({ research: null, works: new Set() })
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

  const renderRow = (entry: LibraryEntry, key: string, researchId: string | null) => <tr key={key}
              className={[entry.work_id === selected ? 'is-selected' : '', dragging?.workId === entry.work_id ? 'is-dragging' : '',
                picksIn(researchId).has(entry.work_id) ? 'is-picked' : ''].join(' ')}
              draggable onDragStart={event => startDrag(event, entry)} onDragEnd={endDrag}
              onClick={() => openWork(entry)}>
              <td className="library-col-pick" onClick={event => event.stopPropagation()}>
                <input type="checkbox" checked={picksIn(researchId).has(entry.work_id)}
                  onChange={() => togglePick(entry.work_id, researchId)}
                  aria-label={t('Select “{title}”', { title: shortTitle(entry.title) })} />
              </td>
              <td className="library-col-paper">
                <GripVertical size={13} className="library-grip" aria-hidden />
                <button type="button" className="library-title" onClick={() => openWork(entry)}
                  aria-expanded={entry.work_id === selected} title={entry.title}>
                  <SourceKey value={entry.source_key} /><span>{entry.title}</span>
                </button>
                <div className="source-byline library-byline">
                  <span>{authorsText(entry.authors)}</span>
                  {entry.venue && <span><em>{entry.venue}</em></span>}
                </div>
                <div className="source-status library-row-facts">
                  {entry.versions.map(version => <span key={version.source_version_id}
                    className={`source-fact is-${version.version_label ? versionTones[version.version_label] ?? 'unstated' : 'unstated'}`}>
                    {entry.versions.length > 1
                      ? `${versionText(version.version_label)} · ${t(ACCESS_LABELS[version.access_level])}`
                      : versionText(version.version_label)}</span>)}
                </div>
              </td>
              <td className="library-col-access"><AccessTag level={entry.access_level} /></td>
              <td className="library-col-year">{yearText(entry.year)}</td>
              <td className="library-col-citations">{entry.cited_by_count !== null ? entry.cited_by_count.toLocaleString(uiLocale()) : t('—')}</td>
              <td className="library-col-projects" title={entry.researches.map(r => r.title).join(' · ')}>
                {entry.researches.length === 1 ? entry.researches[0].title : t('{n} projects', { n: entry.researches.length })}
              </td>
              <td className="library-col-added">{dateText(entry.newest_source_at)}</td>
              <td className="library-col-actions" onClick={event => event.stopPropagation()}>
                <button type="button" className="library-remove" onClick={() => setPending({ research: researchId, works: [entry.work_id] })}
                  aria-label={researchId ? t('Remove from this project') : t('Remove from the Library')}
                  title={researchId ? t('Remove from this project') : t('Remove from the Library')}><Trash2 size={14} aria-hidden /></button>
              </td>
            </tr>

  return <section className="collection library-page">
    <h1>{t('Library')}</h1>
    <p>{t('Every work saved across your research, with its versions and the projects that use it. Citation counts come from OpenAlex and are metadata, not a quality judgment.')}</p>
    {counts && <p className="library-facts">
      <strong>{t('{shown} of {total} works', { shown: filtered.length.toLocaleString(uiLocale()), total: counts.works.toLocaleString(uiLocale()) })}</strong>
      <span aria-hidden="true">·</span>
      <span>{t('{n} versions', { n: counts.versions.toLocaleString(uiLocale()) })}</span>
      <span aria-hidden="true">·</span>
      <span>{t('{n} projects', { n: counts.researches.toLocaleString(uiLocale()) })}</span>
    </p>}

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
      <div className="library-density library-view-controls" role="group" aria-label={t('Row density')}>
        <button type="button" aria-pressed={density === 'comfortable'} onClick={() => chooseDensity('comfortable')}
          aria-label={t('Comfortable rows')} title={t('Comfortable rows')}><Rows2 size={14} aria-hidden /></button>
        <button type="button" aria-pressed={density === 'compact'} onClick={() => chooseDensity('compact')}
          aria-label={t('Compact rows')} title={t('Compact rows')}><Rows3 size={14} aria-hidden /></button>
      </div>
      <div className="library-density" role="group" aria-label={t('Group works')}>
        <button type="button" className="library-group-choice" aria-pressed={grouping === 'project'} onClick={() => chooseGrouping('project')}>{t('By project')}</button>
        <button type="button" className="library-group-choice" aria-pressed={grouping === 'none'} onClick={() => chooseGrouping('none')}>{t('All works')}</button>
      </div>
    </div>

    {error && <Notice tone="error">{t('Could not load the Library: {message}', { message: error })} <Button variant="outline" onClick={() => { setError(''); load() }}>{t('Retry')}</Button></Notice>}
    {!error && entries === null && <p className="library-status" role="status">{t('Loading Library…')}</p>}
    {!error && entries !== null && !filtered.length && <p className="library-status">{query || access !== 'all' ? t('No work matches the current search and filter.') : t('No works yet. Sources you save in a research will appear here.')}</p>}

    {dragging && grouping === 'none' && <div className="library-dock" role="region" aria-label={t('Projects to drop on')}>
      <span className="library-dock-label">{t('Drop on a project to include “{title}” as a source', { title: dragging.title })}</span>
      <div className="library-dock-targets">
        {researches.map(research => <div key={research.id} className="library-dock-target" title={research.title} {...dropProps(research)}>{research.title}</div>)}
      </div>
    </div>}

    {workError && <Notice tone="error">{t('Could not load this work: {message}', { message: workError })}</Notice>}
    {!error && filtered.length > 0 && <div className="library-layout">
      <div className="library-table-wrap" data-density={density} data-grouping={grouping}>
        <table className="library-table">
          <thead>
            <tr>
              <th scope="col" className="library-col-pick"><span className="sr-only">{t('Select')}</span></th>
              {sortable('title', 'Paper', 'Sort by paper title', 'library-col-paper')}
              <th scope="col" className="library-col-access">{t('Reading depth')}</th>
              {sortable('year', 'Year', 'Sort by year', 'library-col-year')}
              {sortable('citations', 'Citations', 'Sort by citation count', 'library-col-citations')}
              <th scope="col" className="library-col-projects">{t('Projects')}</th>
              {sortable('added', 'Added', 'Sort by the date the work was saved', 'library-col-added')}
              <th scope="col" className="library-col-actions"><span className="sr-only">{t('Remove')}</span></th>
            </tr>
          </thead>
          {grouping === 'none' && <tbody>
            {filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(entry => renderRow(entry, entry.work_id, null))}
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
                    <input type="checkbox" className="library-group-pick"
                      checked={rows.length > 0 && rows.every(entry => picksIn(research.id).has(entry.work_id))}
                      ref={box => { if (box) box.indeterminate = picksIn(research.id).size > 0 && !rows.every(entry => picksIn(research.id).has(entry.work_id)) }}
                      disabled={!rows.length}
                      onChange={() => togglePickAll(research.id, rows.map(entry => entry.work_id))}
                      aria-label={t('Select every work in {project}', { project: research.title })} />
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
                    <DropdownMenu>
                      <DropdownMenuTrigger className="library-group-more" aria-label={t('Actions for {title}', { title: research.title })} title={t('More actions')}><Ellipsis size={15} /></DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-auto">
                        <DropdownMenuItem variant="destructive" onClick={() => trashProject(research)}><Trash2 size={15} />{t('Move to Trash')}</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </th>
              </tr>
              {!isFolded && !rows.length && <tr className="library-group-empty"><td colSpan={8}><span>{narrowed ? t('No work in this project matches the current search and filter.') : t('No sources yet. Drag a work here to include it.')}</span></td></tr>}
              {!isFolded && rows.slice(groupPage * GROUP_PAGE_SIZE, (groupPage + 1) * GROUP_PAGE_SIZE).map(entry => renderRow(entry, `${research.id}:${entry.work_id}`, research.id))}
              {!isFolded && rows.length > GROUP_PAGE_SIZE && <tr className="library-group-pager"><td colSpan={8}>
                <Pager page={groupPage} total={rows.length} size={GROUP_PAGE_SIZE} label={t('Pages of {project}', { project: research.title })}
                  onPage={next => setGroupPages(current => ({ ...current, [research.id]: next }))} />
              </td></tr>}
            </tbody>
          })}
        </table>
        {grouping === 'none' && <Pager page={currentPage} total={filtered.length} size={PAGE_SIZE} onPage={setPage} label={t('Library pages')} />}
      </div>

    </div>}

    {selected && sheet && <PassageSheet researchId={sheet.researchId} passageId={sheet.passageId} assetId={sheet.assetId}
      dark={dark} onClose={() => setSelected(null)} />}

    {picked.works.size > 0 && <div className="library-picked" role="status">
      <div className="library-picked-main">
        <span className="library-picked-count">{t('{n} selected', { n: picked.works.size })}</span>
        {picked.research
          ? <span className="library-picked-project" title={projectTitle(picked.research)}>
            <Folder size={12} aria-hidden />
            <span className="sr-only">{t('Project')}</span>
            <span>{projectTitle(picked.research)}</span>
          </span>
          : <span className="library-picked-scope">{t('across every project that uses them')}</span>}
        <span className="library-picked-divider" aria-hidden="true" />
        <Button variant="outline" size="sm" onClick={() => setPending({ research: picked.research, works: [...picked.works] })}>
          <Trash2 size={14} />{picked.research ? t('Remove from the project') : t('Remove from the Library')}
        </Button>
        <Button variant="ghost" size="sm" onClick={clearPicks}>{t('Clear')}<kbd className="library-picked-key">Esc</kbd></Button>
      </div>
      <p className="library-picked-note">
        <Info size={13} aria-hidden />
        <span>
          {offPagePicks > 0 && `${t('{n} of them are on other pages.', { n: offPagePicks })} `}
          {picked.research
            ? t('Removing takes each work out of this project only; the record and its files stay in the Library.')
            : t('Every project that uses them loses them as a source; the records and their files stay in the Library.')}
        </span>
      </p>
    </div>}

    <ConfirmDialog open={pending !== null} dark={dark} neutral busy={removing}
      title={pending?.research ? t('Remove from this project?') : t('Remove from the Library?')}
      description={pending?.research
        ? t('Every stored version leaves this project’s sources. The record, its PDFs and the answers and cells that cite it stay; Undo in the notification brings it back.')
        : t('Every stored version leaves every project that uses the work. The record, its PDFs and the answers and cells that cite it stay; Undo in the notification brings it back.')}
      context={pending ? (pending.works.length === 1
        ? shortTitle(entries?.find(e => e.work_id === pending.works[0])?.title ?? '')
        : t('{n} works', { n: pending.works.length })) : undefined}
      confirmLabel={t('Remove')} cancelLabel={t('Cancel')}
      onConfirm={() => { if (pending) void removeWorks(pending) }}
      onOpenChange={open => { if (!open) setPending(null) }} />
  </section>
}

function sheetTarget(work: LibraryWork | null) {
  const withPdf = work?.versions.find(version => version.research_id && version.asset)
  if (withPdf) return { researchId: withPdf.research_id as string, assetId: (withPdf.asset as { id: string }).id, passageId: null }
  const withAbstract = work?.versions.find(version => version.abstract_passage_id && (version.research_id ?? version.removed_research_id))
  if (withAbstract) return { researchId: (withAbstract.research_id ?? withAbstract.removed_research_id) as string, assetId: null, passageId: withAbstract.abstract_passage_id }
  return null
}
