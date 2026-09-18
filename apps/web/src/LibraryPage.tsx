import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import {
  Check, ChevronDown, ChevronLeft, ChevronRight, Copy, Ellipsis, ExternalLink, Folder, GripVertical,
  Plus, Search, Trash2, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
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

type SortKey = 'added' | 'title' | 'year' | 'citations'
type SortDir = 'asc' | 'desc'
type Sort = { key: SortKey; dir: SortDir }
type SortValue = 'added:desc' | 'added:asc' | 'title:asc' | 'year:desc' | 'citations:desc'
type AccessFilter = AccessLevel | 'all'
type Density = 'comfortable' | 'compact'
type Grouping = 'project' | 'none'
type Dragging = { workId: string; title: string; researchIds: string[] }
// Removing works takes them out of one project, or out of every project that uses them in the all-works view (D50);
// research = null is that library-wide scope. Picking in another project starts the selection again there.
type Picked = { research: string | null; works: Set<string> }
type Pending = { research: string | null; works: string[] }
// One project's rows. A work is listed under a single project, so the bands partition the list instead of repeating works.
type Band = { id: string; title: string; research: LibraryResearch | null; entries: LibraryEntry[] }
type DropProps = {
  onDragOver?: (event: DragEvent) => void
  onDragLeave?: (event: DragEvent) => void
  onDrop?: (event: DragEvent) => void
  'data-drop'?: string
}

const DENSITY_KEY = 'deixis-library-density'
const GROUPING_KEY = 'deixis-library-grouping'
const FOLDED_KEY = 'deixis-library-folded'
const SORT_KEY = 'deixis-library-sort'
const PAGE_SIZE_KEY = 'deixis-library-page-size'
const PAGE_SIZES = [25, 50, 100]
// A project reveals its rows in steps, so a drop target stays reachable without a second pager to interpret.
const BAND_STEP = 10
const WORK_TYPE = 'application/x-deixis-work'

// Reading depth, not quality: what DEIXIS actually stored for this version.
const ACCESS_LABELS: Record<AccessLevel, string> = {
  pdf_available: 'PDF text',
  abstract: 'Abstract only',
  metadata: 'Metadata only',
}
const ACCESS_PILLS: Record<AccessLevel, string> = {
  pdf_available: 'is-text',
  abstract: 'is-abstract',
  metadata: 'is-unstated',
}
const SORT_OPTIONS: { value: SortValue; label: string }[] = [
  { value: 'added:desc', label: 'Added, newest first' },
  { value: 'added:asc', label: 'Added, oldest first' },
  { value: 'title:asc', label: 'Title A–Z' },
  { value: 'year:desc', label: 'Year, newest first' },
  { value: 'citations:desc', label: 'Citations, most cited' },
]
const DEFAULT_SORT: Sort = { key: 'added', dir: 'desc' }

function readStored(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
function writeStored(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* the choice still applies for this tab */ }
}
function readSort(): Sort {
  const stored = readStored(SORT_KEY) as SortValue | null
  const match = SORT_OPTIONS.find(option => option.value === stored)
  if (!match) return DEFAULT_SORT
  const [key, dir] = match.value.split(':') as [SortKey, SortDir]
  return { key, dir }
}
function readPageSize(): number {
  const stored = Number(readStored(PAGE_SIZE_KEY))
  return PAGE_SIZES.includes(stored) ? stored : PAGE_SIZES[0]
}
function readFolded(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(readStored(FOLDED_KEY) ?? '[]')
    return new Set(Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [])
  } catch { return new Set() }
}
function writeFolded(folded: Set<string>) {
  writeStored(FOLDED_KEY, JSON.stringify([...folded]))
}

const compareTitle = (a: LibraryEntry, b: LibraryEntry) => a.title.localeCompare(b.title, uiLocale())
const compareYear = (a: LibraryEntry, b: LibraryEntry) => (a.year ?? -1) - (b.year ?? -1)
const compareCitations = (a: LibraryEntry, b: LibraryEntry) => (a.cited_by_count ?? -1) - (b.cited_by_count ?? -1)
const compareAdded = (a: LibraryEntry, b: LibraryEntry) => a.newest_source_at.localeCompare(b.newest_source_at)

const authorsText = (authors: string[]) => (authors.length ? authors.join(', ') : t('Authors not stated'))
const yearText = (year: number | null) => (year ? String(year) : t('—'))
const dateText = (iso: string) => (iso ? new Date(iso).toLocaleDateString(uiLocale(), { dateStyle: 'medium' }) : t('—'))
const shortTitle = (title: string) => (title.length > 70 ? `${title.slice(0, 69)}…` : title)
const pageCount = (total: number, size: number) => Math.max(1, Math.ceil(total / size))

// How many of a project's rows are revealed: none while folded, otherwise a growing window capped at what it holds.
function bandWindow(band: Band, folded: ReadonlySet<string>, shown: Record<string, number>): number {
  return folded.has(band.id) ? 0 : Math.min(shown[band.id] ?? BAND_STEP, band.entries.length)
}

// At most five numbered pages around the current one, with the ends kept a click away.
function pagerItems(page: number, pages: number): (number | 'gap')[] {
  const wanted = new Set<number>([0, pages - 1, page, page - 1, page + 1, page - 2, page + 2])
  const numbers = [...wanted].filter(item => item >= 0 && item < pages).sort((a, b) => a - b)
  const items: (number | 'gap')[] = []
  for (const item of numbers) {
    if (items.length && item - (items[items.length - 1] as number) > 1) items.push('gap')
    items.push(item)
  }
  return items
}

const NO_PICKS: ReadonlySet<string> = new Set<string>()

// `researchKey` changes when a research is trashed, restored or deleted elsewhere in the app, so the
// Library reloads instead of keeping rows of a research that is no longer in the workspace.
export function LibraryPage({ dark, researchKey, onChanged, onOpenResearch, onStartResearch }: {
  dark: boolean
  researchKey: string
  onChanged: () => void
  onOpenResearch: (id: string) => void
  onStartResearch?: () => void
}) {
  const toast = useToast()
  const [entries, setEntries] = useState<LibraryEntry[] | null>(null)
  const [researches, setResearches] = useState<LibraryResearch[]>([])
  const [counts, setCounts] = useState<{ works: number; versions: number; researches: number } | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [access, setAccess] = useState<AccessFilter>('all')
  const [sort, setSort] = useState<Sort>(readSort)
  const [density, setDensity] = useState<Density>(() => (readStored(DENSITY_KEY) === 'compact' ? 'compact' : 'comfortable'))
  const [grouping, setGrouping] = useState<Grouping>(() => (readStored(GROUPING_KEY) === 'none' ? 'none' : 'project'))
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(readPageSize)
  // How many rows of each band are revealed. A band starts at one step and grows, so nothing is paged twice.
  const [shown, setShown] = useState<Record<string, number>>({})
  const [folded, setFolded] = useState<Set<string>>(readFolded)
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
  const searchRef = useRef<HTMLInputElement>(null)
  const sectionRef = useRef<HTMLElement>(null)
  // The row whose title holds focus, so `x` can pick it without a second selection model to keep in sync.
  const cursorRef = useRef<{ work: string; scope: string | null } | null>(null)

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
    // A folded project that is no longer in the Library would fold again if it came back under the same id.
    setFolded(current => {
      const next = new Set([...current].filter(id => view.researches.some(research => research.id === id)))
      if (next.size === current.size) return current
      writeFolded(next)
      return next
    })
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

  // `/`, the arrow keys and `x` cover the same four moves the key strip names. Text fields keep their own keys,
  // and a dialog or menu keeps every key while it is open.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (document.querySelector('[role="dialog"],[role="menu"]')) return
      const target = event.target as HTMLElement | null
      const inField = !!target && target !== searchRef.current && !!target.closest('input, textarea, select, [contenteditable="true"]')
      if (event.key === '/') {
        if (inField) return
        event.preventDefault()
        searchRef.current?.focus()
        searchRef.current?.select()
        return
      }
      if (inField) return
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        const titles = [...(sectionRef.current?.querySelectorAll<HTMLButtonElement>('button.library-title') ?? [])]
        if (!titles.length) return
        event.preventDefault()
        const from = titles.indexOf(document.activeElement as HTMLButtonElement)
        const step = event.key === 'ArrowDown' ? 1 : -1
        titles[((from < 0 ? (step > 0 ? -1 : 0) : from) + step + titles.length) % titles.length].focus()
        return
      }
      // `x` picks the focused row; without focus on a title there is no row to pick.
      if (event.key === 'x' || event.key === 'X') {
        const cursor = cursorRef.current
        if (!cursor || !target || !target.classList.contains('library-title')) return
        event.preventDefault()
        togglePick(cursor.work, cursor.scope)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Any change to what the list contains or how it is ordered starts again from the first page and clears the picks.
  function resetList() {
    setPage(0)
    setShown({})
    setPicked({ research: null, works: new Set() })
  }
  // Changing how many rows fit on a page moves nothing out of the Library, so the picks survive it.
  function resetView() {
    setPage(0)
    setShown({})
  }

  function chooseGrouping(next: Grouping) {
    setGrouping(next)
    writeStored(GROUPING_KEY, next)
    resetList()
  }
  function chooseDensity(next: Density) {
    setDensity(next)
    writeStored(DENSITY_KEY, next)
  }
  function chooseSort(value: string) {
    const match = SORT_OPTIONS.find(option => option.value === value)
    if (!match) return
    const [key, dir] = match.value.split(':') as [SortKey, SortDir]
    setSort({ key, dir })
    writeStored(SORT_KEY, match.value)
    resetList()
  }
  function chooseAccess(next: AccessFilter) {
    setAccess(next)
    resetList()
  }
  function choosePageSize(size: number) {
    setPageSize(size)
    writeStored(PAGE_SIZE_KEY, String(size))
    resetView()
  }

  function toggleFold(id: string) {
    if (!id) return
    setFolded(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id); else next.add(id)
      writeFolded(next)
      return next
    })
  }
  function showMore(id: string, total: number) {
    setShown(current => ({ ...current, [id]: Math.min((current[id] ?? BAND_STEP) + BAND_STEP, total) }))
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

  // The bar's picker sends every picked work one by one. Works that fail keep their pick, so a retry sends exactly those.
  async function addPicked(research: LibraryResearch) {
    const works = [...picked.works]
    if (!works.length || adding) return
    setAdding(true)
    const failed: string[] = []
    let added = 0
    let skipped = 0
    let depth: AccessLevel | null = null
    try {
      for (const workId of works) {
        const entry = entries?.find(item => item.work_id === workId)
        if (!entry || entry.researches.some(r => r.id === research.id)) { skipped++; continue }
        try {
          const result = await api.addLibrarySource(research.id, workId)
          show(result.library)
          added++
          depth = result.access_level
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) skipped++
          else failed.push(workId)
        }
      }
    } finally {
      setAdding(false)
    }
    setPicked(current => ({ research: current.research, works: new Set(failed) }))
    if (failed.length) {
      toast('warning', t('{n} works could not be added.', { n: failed.length }))
      load()
    } else if (!added) {
      toast('warning', t('All {n} works were already sources in this project.', { n: works.length }))
    } else if (added === 1) {
      toast('success', t('Added to {project} as a source you included ({depth}).', {
        project: shortTitle(research.title), depth: t(ACCESS_LABELS[depth ?? 'metadata']),
      }))
    } else {
      toast('success', t('Added {n} works to {project} as sources you included.', { n: added, project: shortTitle(research.title) }))
    }
  }

  async function copyDoi(doi: string) {
    try {
      await navigator.clipboard.writeText(doi)
      toast('success', t('DOI copied.'))
    } catch (e) {
      toast('error', t('Could not copy the DOI: {message}', { message: (e as Error).message }))
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
  // Drop handlers for one project: a work that is already its source is not a valid drop there. Research-less rows
  // (a work no project holds any more) are not a target at all.
  const dropProps = (research: LibraryResearch | null): DropProps => research === null ? {} : {
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
  }

  const picksIn = (researchId: string | null) => (picked.research === researchId ? picked.works : NO_PICKS)
  const clearPicks = () => setPicked({ research: null, works: new Set() })

  function togglePick(workId: string, researchId: string | null) {
    setPicked(current => {
      const works = current.research === researchId ? new Set(current.works) : new Set<string>()
      if (works.has(workId)) works.delete(workId); else works.add(workId)
      return { research: researchId, works }
    })
  }
  // The project's box picks every work it holds, or clears them when they are all picked already.
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

  const narrowed = query.trim() !== '' || access !== 'all'

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

  // Each work is listed under one project: the one with the most recent activity that still holds it (the server
  // sorts a work's researches by update time, newest first). A work no project holds keeps its own band, and the
  // projects that match nothing stay visible so a drag still has somewhere to land.
  const bands = useMemo<Band[]>(() => {
    if (grouping !== 'project') return []
    const byResearch: Band[] = researches.map(research => ({ id: research.id, title: research.title, research, entries: [] }))
    const known = new Map(byResearch.map(band => [band.id, band]))
    const loose: Band = { id: '', title: t('No project'), research: null, entries: [] }
    for (const entry of filtered) {
      const owner = entry.researches[0]?.id
      const band = owner ? known.get(owner) : undefined
      if (band) band.entries.push(entry)
      else loose.entries.push(entry)
    }
    const visible = narrowed ? byResearch.filter(band => band.entries.length || dragging) : byResearch
    return loose.entries.length ? [...visible, loose] : visible
  }, [researches, filtered, grouping, narrowed, dragging])

  const depths = useMemo(() => {
    const total = { pdf_available: 0, abstract: 0, metadata: 0 }
    for (const entry of entries ?? []) total[entry.access_level]++
    return total
  }, [entries])

  // The provider reads a citation count on a date; the newest of those reads is the one the note can claim.
  const citationsReadAt = useMemo(() => (entries ?? []).reduce<string | null>(
    (latest, entry) => (entry.cited_by_count_at && (!latest || entry.cited_by_count_at > latest) ? entry.cited_by_count_at : latest),
    null), [entries])

  const pages = pageCount(filtered.length, pageSize)
  const currentPage = Math.min(page, pages - 1)
  const flatRows = useMemo(
    () => (grouping === 'none' ? filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize) : []),
    [filtered, grouping, currentPage, pageSize])

  const windowSize = (band: Band) => bandWindow(band, folded, shown)

  // A project's box picks every work it holds while only part of its rows is revealed, so the count in the bar can be
  // larger than what is on screen. This is how many of the picked works the user cannot currently see.
  const onScreen = useMemo(() => {
    const ids = new Set<string>()
    if (grouping === 'none') for (const entry of flatRows) ids.add(entry.work_id)
    else for (const band of bands) for (const entry of band.entries.slice(0, bandWindow(band, folded, shown))) ids.add(entry.work_id)
    return ids
  }, [grouping, flatRows, bands, folded, shown])
  const offScreenPicks = picked.works.size ? [...picked.works].filter(workId => !onScreen.has(workId)).length : 0

  const renderRow = (entry: LibraryEntry, key: string, scope: string | null) => {
    const picks = picksIn(scope)
    const pickable = scope !== null
    // Every project that could take this work, and the projects that already hold it.
    const eligible = researches.filter(research => !entry.researches.some(held => held.id === research.id))
    const owner = (scope ? researches.find(research => research.id === scope) : entry.researches[0]) ?? null
    const added = dateText(entry.newest_source_at)
    return <li key={key}
      className={['library-record', picks.has(entry.work_id) ? 'is-picked' : '', dragging?.workId === entry.work_id ? 'is-dragging' : ''].join(' ').trim()}
      draggable onDragStart={event => startDrag(event, entry)} onDragEnd={endDrag}>
      <input type="checkbox" className="library-check" disabled={!pickable}
        checked={pickable && picks.has(entry.work_id)}
        onChange={() => togglePick(entry.work_id, scope)}
        aria-label={t('Select “{title}”', { title: shortTitle(entry.title) })} />
      <span className="library-grip" role="img" aria-label={t('Drag to add to another project')} title={t('Drag to add to another project')}><GripVertical size={16} aria-hidden /></span>
      <div className="library-body">
        <div className="library-title-row">
          <SourceKey value={entry.source_key} className="library-source-key" />
          <button type="button" className="library-title" onClick={() => openWork(entry)}
            onFocus={() => { cursorRef.current = { work: entry.work_id, scope } }}
            aria-expanded={entry.work_id === selected} title={t('Open the stored passages for this work')}>
            <span>{entry.title}</span>
          </button>
        </div>
        <span className="library-byline">
          <span>{authorsText(entry.authors)}</span>
          {entry.year !== null && <span> · {yearText(entry.year)}</span>}
          {entry.venue && <span> · <em>{entry.venue}</em></span>}
        </span>
        <div className="library-row-facts">
          <span className={`ref-pill library-depth ${ACCESS_PILLS[entry.access_level]}`}>
            <Check size={12} aria-hidden />{t(ACCESS_LABELS[entry.access_level])}
          </span>
          {entry.versions.map(version => <span key={version.source_version_id}
            className={`ref-pill ${version.version_label ? versionTones[version.version_label] ?? 'is-unstated' : 'is-unstated'}`}>
            {entry.versions.length > 1
              ? `${versionText(version.version_label)} · ${t(ACCESS_LABELS[version.access_level])}`
              : versionText(version.version_label)}</span>)}
          <span className="source-fact is-plain">{t('Added {date}', { date: added })}</span>
          {entry.researches.length > 1 && <span className="source-fact is-plain">{t('in {n} projects', { n: entry.researches.length })}</span>}
        </div>
      </div>
      <div className="library-tail">
        {entry.cited_by_count === null
          ? <span className="library-cites" title={t('No citation count recorded by the provider.')}>
            <span className="library-cites-n">—</span><span className="library-cites-u">{t('Citations')}</span>
          </span>
          : <span className="library-cites">
            <span className="library-cites-n">{entry.cited_by_count.toLocaleString(uiLocale())}</span>
            <span className="library-cites-u">{t('Citations')}</span>
          </span>}
        <DropdownMenu>
          <DropdownMenuTrigger className="library-more" aria-label={t('More actions for “{title}”', { title: shortTitle(entry.title) })} title={t('More actions')}>
            <Ellipsis size={16} />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-auto library-menu">
            <DropdownMenuLabel>{t('Add to a project')}</DropdownMenuLabel>
            {!eligible.length && <p className="library-menu-note">{t('No project can take this work.')}</p>}
            {eligible.map(research => <DropdownMenuItem key={research.id} disabled={adding} onClick={() => void addToResearch(entry.work_id, research)}>
              <Folder size={15} /><span className="library-tx">{research.title}</span>
            </DropdownMenuItem>)}
            {entry.researches.map(research => <DropdownMenuItem key={research.id} disabled>
              <Check size={15} /><span className="library-tx">{research.title}</span>
              <span className="library-menu-hint">{t('already a source')}</span>
            </DropdownMenuItem>)}
            <DropdownMenuSeparator />
            {owner && <DropdownMenuItem onClick={() => onOpenResearch(owner.id)}>
              <ExternalLink size={15} /><span className="library-tx">{t('Open in {project}', { project: shortTitle(owner.title) })}</span>
            </DropdownMenuItem>}
            <DropdownMenuItem disabled={!entry.doi} onClick={() => { if (entry.doi) void copyDoi(entry.doi) }}>
              <Copy size={15} /><span className="library-tx">{t('Copy DOI')}</span>
              {!entry.doi && <span className="library-menu-hint">{t('no DOI stored')}</span>}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => setPending({ research: scope, works: [entry.work_id] })}>
              <Trash2 size={15} /><span className="library-tx">{scope ? t('Remove from this project') : t('Remove from the Library')}</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  }

  const renderBand = (band: Band) => {
    const research = band.research
    const isFolded = folded.has(band.id)
    const size = windowSize(band)
    const rest = band.entries.length - size
    const pdf = band.entries.filter(entry => entry.access_level === 'pdf_available').length
    return <li className="library-band" key={band.id || 'none'} data-band={band.id || 'none'} {...dropProps(research)}>
      <div className="library-band-head">
        <input type="checkbox" className="library-band-pick"
          checked={!!band.entries.length && band.entries.every(entry => picksIn(band.id).has(entry.work_id))}
          ref={box => { if (box) box.indeterminate = picksIn(band.id).size > 0 && !band.entries.every(entry => picksIn(band.id).has(entry.work_id)) }}
          disabled={!research || !band.entries.length}
          onChange={() => togglePickAll(band.id, band.entries.map(entry => entry.work_id))}
          aria-label={t('Select every work in {project}', { project: band.title })} />
        <button type="button" className="library-fold" onClick={() => toggleFold(band.id)} disabled={!research}
          aria-expanded={!isFolded} title={band.title}>
          <span className="library-caret">{isFolded ? <ChevronRight size={16} aria-hidden /> : <ChevronDown size={16} aria-hidden />}</span>
          <span className="library-band-title">{band.title}</span>
        </button>
        {research && <span className="library-dropnote">{t('Drop to include as a source')}</span>}
        {research && <span className="library-dropnote library-dropnote-has">{t('Already a source')}</span>}
        <span className="library-band-facts">
          <span>{narrowed
            ? t('{n} matching works', { n: band.entries.length.toLocaleString(uiLocale()) })
            : t('{n} works', { n: band.entries.length.toLocaleString(uiLocale()) })}</span>
          <span>{t('{n} with PDF text', { n: pdf })}</span>
        </span>
        <span className="library-band-actions">
          {research && <button type="button" className="library-open" onClick={() => onOpenResearch(research.id)}>{t('Open research')}</button>}
          {research && <DropdownMenu>
            <DropdownMenuTrigger className="library-more" aria-label={t('Actions for {title}', { title: band.title })} title={t('More actions')}><Ellipsis size={16} /></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-auto library-menu">
              <DropdownMenuItem onClick={() => onOpenResearch(research.id)}><ExternalLink size={15} /><span className="library-tx">{t('Open research')}</span></DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" disabled={!!dragging} onClick={() => trashProject(research)}>
                <Trash2 size={15} /><span className="library-tx">{t('Move to Trash')}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>}
        </span>
      </div>
      {!isFolded && !!band.entries.length && <ul className="library-records">
        {band.entries.slice(0, size).map(entry => renderRow(entry, `${band.id || 'none'}:${entry.work_id}`, band.id || null))}
      </ul>}
      {!isFolded && !band.entries.length && <p className="library-bandmore">
        {narrowed
          ? t('No work in this project matches the current search and filter.')
          : t('No rows here yet. Each work is listed under one project, the one most recently active that holds it.')}
      </p>}
      {!isFolded && rest > 0 && <p className="library-bandmore">
        <span>{narrowed
          ? t('Showing {shown} of {total} matching rows in this project', { shown: size, total: band.entries.length })
          : t('Showing {shown} of {total} rows in this project', { shown: size, total: band.entries.length })}</span>
        <Button variant="outline" size="sm" onClick={() => showMore(band.id, band.entries.length)}>
          {t('Show {n} more', { n: Math.min(BAND_STEP, rest) })}
        </Button>
      </p>}
    </li>
  }

  // The projects a drag can still land on: the ones that do not already hold the work.
  const draggable = dragging ? researches.filter(research => !dragging.researchIds.includes(research.id)) : []

  return <section className="collection library-page" ref={sectionRef} data-density={density} data-grouping={grouping}>
    <div className="library-mast">
      <h1>{t('Library')}</h1>
      <p className="library-lede">{t('Every work saved across your research, with its versions and the projects that use it. Citation counts come from OpenAlex and are metadata, not a quality judgment.')}</p>
    </div>

    {counts && <ul className="library-rail">
      <li><span className="library-num">{counts.works.toLocaleString(uiLocale())}</span> {t('works')}</li>
      <li><span className="library-num">{counts.versions.toLocaleString(uiLocale())}</span> {t('stored versions')}</li>
      <li><span className="library-num">{counts.researches.toLocaleString(uiLocale())}</span> {t('projects')}</li>
    </ul>}

    {counts && counts.works > 0 && <div className="library-cover">
      <div className="library-cover-bar" role="img"
        aria-label={t('Reading depth across {total} works: {text} with PDF text, {abstract} abstract only, {metadata} metadata only.', {
          total: counts.works.toLocaleString(uiLocale()),
          text: depths.pdf_available.toLocaleString(uiLocale()),
          abstract: depths.abstract.toLocaleString(uiLocale()),
          metadata: depths.metadata.toLocaleString(uiLocale()),
        })}>
        {depths.pdf_available > 0 && <span className="library-c-text" style={{ flex: `${depths.pdf_available} 1 0` }} />}
        {depths.abstract > 0 && <span className="library-c-abstract" style={{ flex: `${depths.abstract} 1 0` }} />}
        {depths.metadata > 0 && <span className="library-c-meta" style={{ flex: `${depths.metadata} 1 0` }} />}
      </div>
      <ul className="library-cover-legend">
        {depths.pdf_available > 0 && <li><i className="library-c-text" aria-hidden />{t('PDF text')} <span className="library-num">{depths.pdf_available.toLocaleString(uiLocale())}</span></li>}
        {depths.abstract > 0 && <li><i className="library-c-abstract" aria-hidden />{t('Abstract only')} <span className="library-num">{depths.abstract.toLocaleString(uiLocale())}</span></li>}
        {depths.metadata > 0 && <li><i className="library-c-meta" aria-hidden />{t('Metadata only')} <span className="library-num">{depths.metadata.toLocaleString(uiLocale())}</span></li>}
      </ul>
      <p className="library-cover-note">
        {t('Depth is what DEIXIS holds for each work, not a claim about the work.')}
        {citationsReadAt && ` ${t('Citation counts come from OpenAlex; the newest was read on {date}.', { date: dateText(citationsReadAt) })}`}
      </p>
    </div>}

    <div className="library-commands">
      <div className="library-search" role="search">
        <Search size={15} aria-hidden />
        <input ref={searchRef} type="search" value={query} onChange={event => { setQuery(event.target.value); resetList() }}
          placeholder={t('Search by title, author, venue, DOI or project')} aria-label={t('Search the library')} />
        <span className="library-slash" aria-hidden>{t('search')} <kbd>/</kbd></span>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger className="library-picker" aria-label={t('Sort works')}>
          <span className="library-lead">{t('Sort')}</span>
          <span className="library-value">{t(SORT_OPTIONS.find(option => option.value === `${sort.key}:${sort.dir}`)?.label ?? SORT_OPTIONS[0].label)}</span>
          <ChevronDown size={14} aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-auto library-menu">
          <DropdownMenuLabel>{t('Sort works')}</DropdownMenuLabel>
          {SORT_OPTIONS.map(option => <DropdownMenuItem key={option.value} onClick={() => chooseSort(option.value)}>
            {`${sort.key}:${sort.dir}` === option.value ? <Check size={15} /> : <span className="library-menu-gap" aria-hidden />}
            <span className="library-tx">{t(option.label)}</span>
          </DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu>
      <DropdownMenu>
        <DropdownMenuTrigger className="library-picker" aria-label={t('Filter by reading depth')}>
          <span className="library-lead">{t('Reading depth')}</span>
          <span className="library-value">{t(access === 'all' ? 'Any depth' : ACCESS_LABELS[access])}</span>
          <ChevronDown size={14} aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-auto library-menu">
          <DropdownMenuLabel>{t('Show works with')}</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => chooseAccess('all')}>
            {access === 'all' ? <Check size={15} /> : <span className="library-menu-gap" aria-hidden />}
            <span className="library-tx">{t('Any depth')}</span>
          </DropdownMenuItem>
          {(['pdf_available', 'abstract', 'metadata'] as AccessLevel[]).map(level => <DropdownMenuItem key={level} onClick={() => chooseAccess(level)}>
            {access === level ? <Check size={15} /> : <span className="library-menu-gap" aria-hidden />}
            <span className="library-tx">{t(ACCESS_LABELS[level])}</span>
            <span className="library-menu-hint">{(entries ?? []).filter(entry => entry.access_level === level).length.toLocaleString(uiLocale())}</span>
          </DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu>
      <div className="library-seg" role="group" aria-label={t('Row density')}>
        <button type="button" aria-pressed={density === 'comfortable'} onClick={() => chooseDensity('comfortable')} title={t('Comfortable rows')}>{t('Comfortable')}</button>
        <button type="button" aria-pressed={density === 'compact'} onClick={() => chooseDensity('compact')} title={t('Compact rows')}>{t('Compact')}</button>
      </div>
      <div className="library-seg" role="group" aria-label={t('Group works')}>
        <button type="button" aria-pressed={grouping === 'project'} onClick={() => chooseGrouping('project')}>{t('By project')}</button>
        <button type="button" aria-pressed={grouping === 'none'} onClick={() => chooseGrouping('none')}>{t('All works')}</button>
      </div>
    </div>

    {narrowed && <div className="library-chiprow">
      <span className="library-chip">
        {query.trim()}
        <button type="button" className="library-chip-x" aria-label={t('Remove search term')} onClick={() => { setQuery(''); resetList() }}><X size={13} aria-hidden /></button>
      </span>
      {access !== 'all' && <span className="library-chip">
        {t(ACCESS_LABELS[access])}
        <button type="button" className="library-chip-x" aria-label={t('Remove reading-depth filter')} onClick={() => chooseAccess('all')}><X size={13} aria-hidden /></button>
      </span>}
      <span className="library-chip-count">{filtered.length === 1 ? t('1 work matches') : t('{n} works match', { n: filtered.length.toLocaleString(uiLocale()) })}</span>
      <button type="button" className="library-clear" onClick={() => { setQuery(''); chooseAccess('all') }}>{t('Clear all')}</button>
    </div>}

    {error && <Notice tone="error">{t('Could not load the Library: {message}', { message: error })} <Button variant="outline" onClick={() => { setError(''); load() }}>{t('Retry')}</Button></Notice>}
    {!error && entries === null && <p className="library-status" role="status">{t('Loading Library…')}</p>}
    {!error && entries !== null && !filtered.length && (narrowed
      ? <p className="library-status" role="status">{t('No work matches the current search and filter.')} <button type="button" className="library-clear" onClick={() => { setQuery(''); chooseAccess('all') }}>{t('Clear all')}</button></p>
      : <div className="library-empty">
        <p>{t('No works yet. Sources you save in a research will appear here.')}</p>
        {onStartResearch && <Button variant="outline" onClick={onStartResearch}><Plus size={14} aria-hidden />{t('Start a research')}</Button>}
      </div>)}

    {dragging && <div className="library-dock">
      <GripVertical size={16} className="library-dock-grip" aria-hidden />
      <span className="library-dock-label">
        <b>{shortTitle(dragging.title)}</b>
        <span>{draggable.length
          ? t('{n} projects can take it', { n: draggable.length })
          : t('Already a source in every project')}</span>
      </span>
      {grouping === 'none' && <div className="library-dock-targets">
        {draggable.map(research => <span key={research.id} className="library-dock-target" title={research.title} {...dropProps(research)}>{research.title}</span>)}
      </div>}
      {grouping === 'none' && <span className="library-drop-hint">{t('Drop it on a project')}</span>}
    </div>}

    {workError && <Notice tone="error">{t('Could not load this work: {message}', { message: workError })}</Notice>}

    {!error && filtered.length > 0 && (grouping === 'none'
      ? <ul className="library-records">
        {flatRows.map(entry => renderRow(entry, entry.work_id, null))}
      </ul>
      : <ul className="library-bands">{bands.map(renderBand)}</ul>)}

    {grouping === 'none' && filtered.length > 0 && pages > 1 && <div className="library-pager">
      <span className="library-range">{t('{first}–{last} of {total}', {
        first: currentPage * pageSize + 1,
        last: Math.min(filtered.length, (currentPage + 1) * pageSize),
        total: filtered.length.toLocaleString(uiLocale()),
      })}</span>
      <div className="library-pages">
        <button type="button" onClick={() => setPage(currentPage - 1)} disabled={currentPage === 0} aria-label={t('Previous page')}><ChevronLeft size={15} aria-hidden /></button>
        {pagerItems(currentPage, pages).map((item, index) => item === 'gap'
          ? <span className="library-page-gap" key={`gap-${index}`} aria-hidden>…</span>
          : <button type="button" key={item} onClick={() => setPage(item)} aria-current={item === currentPage ? 'page' : undefined}>{item + 1}</button>)}
        <button type="button" onClick={() => setPage(currentPage + 1)} disabled={currentPage >= pages - 1} aria-label={t('Next page')}><ChevronRight size={15} aria-hidden /></button>
        <DropdownMenu>
          <DropdownMenuTrigger className="library-more" aria-label={t('Rows per page')}>{t('{n} / page', { n: pageSize })}</DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-auto library-menu">
            <DropdownMenuLabel>{t('Rows per page')}</DropdownMenuLabel>
            {PAGE_SIZES.map(size => <DropdownMenuItem key={size} onClick={() => choosePageSize(size)}>
              {size === pageSize ? <Check size={15} /> : <span className="library-menu-gap" aria-hidden />}
              <span className="library-tx">{t('{n} / page', { n: size })}</span>
            </DropdownMenuItem>)}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>}

    <ul className="library-keystrip">
      <li><kbd>/</kbd>{t('search')}</li>
      <li><kbd>↑</kbd><kbd>↓</kbd>{t('move between works')}</li>
      <li><kbd>x</kbd>{t('pick')}</li>
      <li><kbd>↵</kbd>{t('inspect')}</li>
    </ul>

    {selected && sheet && <PassageSheet researchId={sheet.researchId} passageId={sheet.passageId} assetId={sheet.assetId}
      dark={dark} onClose={() => setSelected(null)} />}

    {picked.works.size > 0 && <div className="library-picked" role="status">
      <span className="library-picked-count">{picked.works.size === 1 ? t('1 work picked') : t('{n} works picked', { n: picked.works.size })}</span>
      <DropdownMenu>
        <DropdownMenuTrigger className="library-picked-add" disabled={adding}>
          <Plus size={14} aria-hidden />{t('Add to a project')}<ChevronDown size={14} aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-auto library-menu">
          <DropdownMenuLabel>{t('Add to a project')}</DropdownMenuLabel>
          {!researches.length && <p className="library-menu-note">{t('No project yet.')}</p>}
          {researches.map(research => <DropdownMenuItem key={research.id} disabled={adding} onClick={() => void addPicked(research)}>
            <Folder size={15} /><span className="library-tx">{research.title}</span>
          </DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu>
      <Button variant="outline" size="sm" onClick={() => setPending({ research: picked.research, works: [...picked.works] })}>
        <Trash2 size={14} aria-hidden />{picked.research ? t('Remove from the project') : t('Remove from the Library')}
      </Button>
      <Button variant="ghost" size="sm" onClick={clearPicks}>{t('Clear')}<kbd className="library-key">Esc</kbd></Button>
      {picked.research
        ? <span className="library-picked-scope" title={projectTitle(picked.research)}>
          <Folder size={12} aria-hidden /><span className="sr-only">{t('Project')}</span><span>{projectTitle(picked.research)}</span>
        </span>
        : <span className="library-picked-scope">{t('across every project that uses them')}</span>}
      <p className="library-picked-note">
        {offScreenPicks > 0 && `${t('Shown rows only: {n} of the picked works are not on screen.', { n: offScreenPicks })} `}
        {picked.research
          ? t('Removing takes each work out of this project only; the record and its files stay in the Library.')
          : t('Every project that uses them loses them as a source; the records and their files stay in the Library.')}
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
