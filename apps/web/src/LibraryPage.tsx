import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react'
import {
  ArrowUpDown, Check, ChevronLeft, ChevronRight, Download, Ellipsis, FileText, Filter, Folder, LibraryBig, Link2,
  MessageSquare, Search, Table2, Trash2, Upload, X,
} from 'lucide-react'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  api, ApiError, libraryApi, libraryImportsApi, type AccessLevel, type LibraryEntry, type LibraryResearch, type LibraryView,
  type LibraryWork, type ModelRole, type RoleModelSetting,
} from './api'
import { ConfirmDialog } from './ConfirmDialog'
import { SourceKey } from './SourceKey'
import { PassageSheet } from './PassageSheet'
import { ZoteroDialog, type ZoteroChoice } from './ZoteroDialog'
import { connectionModels, modelKey, type ConnectionModel } from './Home'
import { defaultEffort, listedEffort } from './modelEffort'
import { versionText } from './labels'
import { t, uiLocale } from './i18n'
import { useToast } from './Toast'
import './LibraryPage.css'

// The Library page (mockup `.lib`, plan L1–L10; UI parity S25): the head with Import from Zotero and Upload PDF, then three
// panes: All works and the researches (200px), the table (search, Sort, PDF filter; Title, Year, Reading depth, Research,
// row menu) and "New from selection" with the reading-depth box (260px). Below 1100px the third pane hides and its actions
// move to a bar under the table; on a phone the left pane hides and a select chooses the research.
//
// Every number comes from the one list the page holds (`/api/library`): "All works" counts its entries, a research counts
// the entries it holds (the rows shown when it is chosen), and the depth box counts every entry by its stored reading
// depth. What an action reports comes from the server's answer, never from what was asked.

type SortKey = 'added_new' | 'added_old' | 'cited' | 'year_new' | 'year_old' | 'title'
type PdfFilter = 'all' | 'text' | 'no_text' | 'abstract' | 'metadata'
type Pending = { research: string | null; works: string[] }
type Mode = 'table' | 'ask'
type Result = { tone: 'ok' | 'warn' | 'bad'; lines: string[]; open?: { id: string; tab?: string } }

const SORT_KEY = 'deixis-library-sort'
const PAGE_SIZE_KEY = 'deixis-library-page-size'
const PAGE_SIZES = [25, 50, 100]
const WORK_TYPE = 'application/x-deixis-work'

// Reading depth is what DEIXIS stores for the work, not a claim about the work: a PDF text layer, an abstract, or the
// bibliographic record alone.
const ACCESS_LABELS: Record<AccessLevel, string> = { pdf_available: 'PDF text', abstract: 'Abstract only', metadata: 'Metadata only' }
const SORTS: Record<SortKey, string> = {
  added_new: 'Recently added', added_old: 'First added', cited: 'Most cited', year_new: 'Newest first', year_old: 'Oldest first', title: 'Title A–Z',
}
const PDF_FILTERS: Record<PdfFilter, string> = { all: 'All', text: 'PDF text', no_text: 'No PDF text', abstract: 'Abstract only', metadata: 'Metadata only' }
const passesPdf = (entry: LibraryEntry, filter: PdfFilter) => filter === 'all' ? true : filter === 'text' ? entry.access_level === 'pdf_available'
  : filter === 'no_text' ? entry.access_level !== 'pdf_available' : filter === 'abstract' ? entry.access_level === 'abstract' : entry.access_level === 'metadata'

function readStored(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
function writeStored(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* the choice still applies in this tab */ }
}
// The earlier Library stored its sort as `key:dir`; those values map to the same order here.
const OLD_SORTS: Record<string, SortKey> = { 'added:desc': 'added_new', 'added:asc': 'added_old', 'title:asc': 'title', 'year:desc': 'year_new', 'citations:desc': 'cited' }
function readSort(): SortKey {
  const stored = readStored(SORT_KEY) ?? ''
  return stored in SORTS ? stored as SortKey : OLD_SORTS[stored] ?? 'added_new'
}
function readPageSize(): number {
  const stored = Number(readStored(PAGE_SIZE_KEY))
  return PAGE_SIZES.includes(stored) ? stored : PAGE_SIZES[0]
}

// Works without the value (no year, no citation count) go last in either direction.
const byNumber = (a: number | null, b: number | null, dir: 1 | -1) => a === null ? (b === null ? 0 : 1) : b === null ? -1 : dir * (a - b)
const COMPARE: Record<SortKey, (a: LibraryEntry, b: LibraryEntry) => number> = {
  added_new: (a, b) => b.newest_source_at.localeCompare(a.newest_source_at),
  added_old: (a, b) => a.newest_source_at.localeCompare(b.newest_source_at),
  cited: (a, b) => byNumber(a.cited_by_count, b.cited_by_count, -1),
  year_new: (a, b) => byNumber(a.year, b.year, -1),
  year_old: (a, b) => byNumber(a.year, b.year, 1),
  title: (a, b) => a.title.localeCompare(b.title, uiLocale()),
}

const authorsText = (authors: string[]) => (authors.length ? authors.join(', ') : t('Authors not stated'))
const shortTitle = (title: string) => (title.length > 70 ? `${title.slice(0, 69)}…` : title)
const num = (n: number) => n.toLocaleString(uiLocale())
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

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

// The model a new research from the Library runs with: the default saved in Settings while its connection still lists
// it, otherwise the connection's own default model, as the Home composer starts. The dialog names it before anything starts.
type ModelChoice = { connection: string; model: string; effort: string | null; name: string; fromSettings: boolean }
function startModel(models: ConnectionModel[], setting: RoleModelSetting | undefined): ModelChoice | null {
  const saved = setting?.model ? modelKey(setting.model_connection, setting.model) : null
  const preferred = models.find(m => m.is_default) ?? models[0]
  const id = saved && models.some(m => m.id === saved) ? saved : preferred?.id
  const chosen = models.find(m => m.id === id)
  if (!chosen) return null
  const effort = (id === saved ? listedEffort(models, chosen.id, setting?.reasoning_effort ?? null) : null) ?? defaultEffort(models, chosen.id)
  return { connection: chosen.connection, model: chosen.model, effort, name: chosen.display_name ?? chosen.model, fromSettings: id === saved }
}

// Counts the records of a bibliography file the server sent: one `@type{` per BibTeX entry, one `TY  -` per RIS record.
const recordsIn = (text: string, format: 'bibtex' | 'ris') => (format === 'bibtex' ? text.match(/^\s*@(?!comment|preamble|string)\w+\s*[{(]/gim) : text.match(/^TY {2}- /gm))?.length ?? 0

export function LibraryPage({ dark, researchKey, onChanged, onOpenResearch }: {
  dark: boolean
  researchKey: string
  onChanged: () => void
  onOpenResearch: (id: string, tab?: string) => void
}) {
  const toast = useToast()
  const [view, setView] = useState<LibraryView | null>(null)
  const [error, setError] = useState('')
  const [project, setProject] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [pdf, setPdf] = useState<PdfFilter>('all')
  const [sort, setSort] = useState<SortKey>(readSort)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(readPageSize)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  // The write that is running, by name; every write control is locked while one runs.
  const [busy, setBusy] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [asking, setAsking] = useState<{ mode: Mode; works: string[] } | null>(null)
  const [dragging, setDragging] = useState<{ workId: string; held: string[] } | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [work, setWork] = useState<LibraryWork | null>(null)
  const [workVersion, setWorkVersion] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)
  const sectionRef = useRef<HTMLElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const zoteroButton = useRef<HTMLButtonElement>(null)
  const cursorRef = useRef<string | null>(null)
  // One version for every read and write of the list (S24 lesson): a write bumps it when it starts and when it ends, and a
  // read applies its answer (or its error) only when no write started, ran or ended meanwhile. The newest write's own
  // answer is shown; an older write that ends later, or a write without a list in its answer, reads the list again.
  const version = useRef(0)
  const writes = useRef(0)
  const writeSeq = useRef(0)

  const entries = useMemo(() => view?.entries ?? [], [view])
  const researches = useMemo(() => view?.researches ?? [], [view])
  const byWork = useMemo(() => new Map(entries.map(entry => [entry.work_id, entry])), [entries])

  function show(next: LibraryView) {
    setView(next)
    setError('')
    const works = new Set(next.entries.map(entry => entry.work_id))
    const ids = new Set(next.researches.map(research => research.id))
    // A research that left the workspace (trashed elsewhere) is no longer a choice; its works stay in All works.
    setProject(current => (current && !ids.has(current) ? null : current))
    // Picks, a confirmation and the new-research dialog keep only works that are still in the Library; one with nothing
    // left closes, so no action runs on works the screen no longer shows.
    setPicked(current => {
      const kept = new Set([...current].filter(id => works.has(id)))
      return kept.size === current.size ? current : kept
    })
    setPending(current => {
      if (!current) return current
      const kept = current.works.filter(id => works.has(id))
      return !kept.length || (current.research && !ids.has(current.research)) ? null : kept.length === current.works.length ? current : { ...current, works: kept }
    })
    setAsking(current => {
      if (!current) return current
      const kept = current.works.filter(id => works.has(id))
      return !kept.length ? null : kept.length === current.works.length ? current : { ...current, works: kept }
    })
    setSelected(current => (current && !works.has(current) ? null : current))
  }

  function load() {
    const seen = version.current
    api.library().then(next => { if (version.current === seen && !writes.current) show(next) })
      .catch((e: Error) => { if (version.current === seen && !writes.current) setError(e.message) })
  }
  useEffect(load, [researchKey])

  async function write<T>(name: string, run: () => Promise<T>, listOf: (answer: T) => LibraryView | undefined = () => undefined): Promise<T> {
    const seq = ++writeSeq.current
    version.current++
    writes.current++
    setBusy(name)
    let shown = false
    try {
      const answer = await run()
      const list = listOf(answer)
      if (list && seq === writeSeq.current) { show(list); shown = true }
      return answer
    } finally {
      writes.current--
      version.current++
      if (!writes.current) setBusy(null)
      if (!shown && !writes.current) load()
    }
  }

  useEffect(() => {
    if (!selected) return
    let current = true
    setWork(null)
    api.libraryWork(selected)
      .then(next => {
        if (!current) return
        if (sheetTarget(next)) { setWork(next); return }
        // A work no research holds or held keeps its text only in the Library, and passages open through a research.
        toast('warning', t('No research holds “{title}”, so its stored text cannot open here.', { title: shortTitle(next.title) }))
        setSelected(null)
      })
      .catch((e: Error) => { if (current) { toast('error', t('Could not load this work: {message}', { message: e.message })); setSelected(null) } })
    return () => { current = false }
  }, [selected, workVersion, toast])

  // `/`, the arrow keys and `x` work as the key line under the table names. Text fields keep their own keys, and a dialog
  // or menu keeps every key while it is open.
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
      if (event.key === 'x' || event.key === 'X') {
        const cursor = cursorRef.current
        if (!cursor || !target || !target.classList.contains('library-title')) return
        event.preventDefault()
        togglePick(cursor)
      }
      if (event.key === 'Escape' && !event.defaultPrevented) setPicked(current => (current.size ? new Set() : current))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // A change to what the table lists starts again from its first page and clears the picks.
  function resetList() {
    setPage(0)
    setPicked(new Set())
  }
  function chooseProject(next: string | null) {
    setProject(next)
    resetList()
  }
  function chooseSort(next: SortKey) {
    setSort(next)
    writeStored(SORT_KEY, next)
    setPage(0)
  }
  function choosePdf(next: PdfFilter) {
    setPdf(next)
    resetList()
  }
  function choosePageSize(size: number) {
    setPageSize(size)
    writeStored(PAGE_SIZE_KEY, String(size))
    setPage(0)
  }
  function togglePick(workId: string) {
    setPicked(current => {
      const next = new Set(current)
      if (next.has(workId)) next.delete(workId); else next.add(workId)
      return next
    })
  }

  const inProject = useMemo(() => (project ? entries.filter(entry => entry.researches.some(r => r.id === project)) : entries), [entries, project])
  const needle = query.trim().toLocaleLowerCase(uiLocale())
  const shown = useMemo(() => {
    const list = inProject.filter(entry => passesPdf(entry, pdf) && (!needle || [entry.title, authorsText(entry.authors), entry.venue ?? '',
      entry.year === null ? '' : String(entry.year), entry.doi ?? '', ...entry.researches.map(r => r.title)].join('\n').toLocaleLowerCase(uiLocale()).includes(needle)))
    return [...list].sort(COMPARE[sort])
  }, [inProject, pdf, needle, sort])
  const pages = Math.max(1, Math.ceil(shown.length / pageSize))
  const currentPage = Math.min(page, pages - 1)
  const rows = shown.slice(currentPage * pageSize, (currentPage + 1) * pageSize)
  const pickedWorks = useMemo(() => [...picked].map(id => byWork.get(id)).filter((e): e is LibraryEntry => Boolean(e)), [picked, byWork])
  const projectTitle = (id: string | null) => (id ? researches.find(r => r.id === id)?.title ?? '' : '')
  const projectName = project ? projectTitle(project) : t('All')
  // Depth over every work in the Library (the box says "all works"), from the stored reading of each.
  const depth = useMemo(() => {
    const total = { pdf_available: 0, abstract: 0, metadata: 0 }
    for (const entry of entries) total[entry.access_level]++
    return total
  }, [entries])
  const citationsReadAt = useMemo(() => entries.reduce<string | null>(
    (latest, entry) => (entry.cited_by_count_at && (!latest || entry.cited_by_count_at > latest) ? entry.cited_by_count_at : latest), null), [entries])
  const heldBy = (researchId: string) => entries.filter(entry => entry.researches.some(r => r.id === researchId)).length
  const narrowed = needle !== '' || pdf !== 'all'
  const locked = busy !== null

  function openWork(entry: LibraryEntry) {
    if (entry.access_level === 'metadata') {
      toast('warning', t('No abstract or PDF text is stored for “{title}”.', { title: shortTitle(entry.title) }))
      return
    }
    setSelected(entry.work_id)
  }

  async function copyDoi(doi: string) {
    try {
      await navigator.clipboard.writeText(doi)
      toast('success', t('DOI copied.'))
    } catch (e) {
      toast('error', t('Could not copy the DOI: {message}', { message: errorText(e) }))
    }
  }

  // Adding a work makes one stored version of it an included source of that research; the backend picks the version.
  async function addWorks(workIds: string[], research: LibraryResearch) {
    if (locked) return
    const todo = workIds.filter(id => byWork.get(id) && !byWork.get(id)!.researches.some(r => r.id === research.id))
    const already = workIds.length - todo.length
    if (!todo.length) {
      toast('warning', workIds.length === 1
        ? t('“{title}” is already in {project}.', { title: shortTitle(byWork.get(workIds[0])?.title ?? ''), project: shortTitle(research.title) })
        : t('All {n} works are already in {project}.', { n: workIds.length, project: shortTitle(research.title) }))
      return
    }
    // Filled inside the write; a holder, so the counts read after it are the ones the requests produced.
    const out = { added: 0, present: already, depth: null as AccessLevel | null, failed: [] as string[], last: undefined as LibraryView | undefined }
    await write('add', async () => {
      for (const workId of todo) {
        try {
          const answer = await api.addLibrarySource(research.id, workId)
          out.last = answer.library
          out.added++
          out.depth = answer.access_level
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) out.present++
          else out.failed.push(errorText(e))
        }
      }
    }, () => out.last).catch(() => undefined)
    if (selected && workIds.includes(selected)) setWorkVersion(v => v + 1)
    setPicked(current => (current.size ? new Set() : current))
    const name = shortTitle(research.title)
    const { added, present, depth: depthOf, failed } = out
    const parts = [
      added === 1 && todo.length === 1 && depthOf ? t('Added to {project} as a source you included ({depth}).', { project: name, depth: t(ACCESS_LABELS[depthOf]) })
        : added ? t('Added {n} works to {project} as sources you included.', { n: added, project: name }) : '',
      present ? t('{n} were already in it.', { n: present }) : '',
      failed.length ? t('{n} could not be added: {message}', { n: failed.length, message: failed[0] }) : '',
    ].filter(Boolean)
    toast(failed.length ? (added ? 'warning' : 'error') : added ? 'success' : 'warning', parts.join(' '))
  }

  // Removal takes every stored version of each work out of one research (or of every research that holds it, in All works).
  // The records, files, answers and cells stay, and the work stays in All works; Undo in the notification puts it back.
  async function removeWorks({ research, works }: Pending) {
    const targets = new Map<string, string[]>()
    for (const workId of works) {
      const entry = byWork.get(workId)
      if (!entry) continue
      // Only the versions each research holds: a research that holds one version of a work does not hold the others.
      for (const rid of research ? [research] : entry.researches.map(r => r.id)) {
        const svids = entry.versions.filter(v => v.research_ids.includes(rid)).map(v => v.source_version_id)
        if (svids.length) targets.set(rid, [...(targets.get(rid) ?? []), ...svids])
      }
    }
    const undo: { research: string; svids: string[] }[] = []
    try {
      await write('remove', async () => {
        for (const [rid, svids] of targets) {
          const answer = await api.removeSources(rid, svids)
          if (answer.changed_source_version_ids.length) undo.push({ research: rid, svids: answer.changed_source_version_ids })
        }
      })
    } catch (e) {
      setPending(null)
      // Any removal that went through before the failure is still offered back.
      toast('error', [t('Could not remove: {message}', { message: errorText(e) }), undo.length ? t('Some works were removed before the error.') : ''].filter(Boolean).join(' '),
        undo.length ? { label: t('Undo'), run: () => void restore(undo) } : undefined)
      return
    }
    setPending(null)
    setPicked(new Set())
    const changed = new Set(undo.flatMap(u => u.svids))
    const removed = works.filter(id => byWork.get(id)?.versions.some(v => changed.has(v.source_version_id)))
    if (!removed.length) { toast('warning', t('Nothing was removed: the works were no longer in that research.')); return }
    const one = removed.length === 1 ? shortTitle(byWork.get(removed[0])?.title ?? '') : null
    const where = research ? shortTitle(projectTitle(research)) : null
    toast('success', where
      ? (one ? t('“{title}” removed from {project}. It stays in All works.', { title: one, project: where })
        : t('{n} works removed from {project}. They stay in All works.', { n: removed.length, project: where }))
      : (one ? t('“{title}” removed from every research that held it. It stays in All works.', { title: one })
        : t('{n} works removed from every research that held them. They stay in All works.', { n: removed.length })),
    { label: t('Undo'), run: () => void restore(undo) })
  }
  async function restore(undo: { research: string; svids: string[] }[]) {
    try {
      await write('restore', () => Promise.all(undo.map(u => api.restoreSources(u.research, u.svids))))
      toast('success', t('Put back.'))
    } catch (e) {
      toast('error', t('Could not put it back: {message}', { message: errorText(e) }))
    }
  }

  function trashProject(research: LibraryResearch) {
    if (locked) return
    write('trash', () => api.moveToTrash(research.id)).then(() => {
      onChanged()
      toast('success', t('Moved to Trash.'), { label: t('Undo'), run: () => {
        write('restore', () => api.restore(research.id)).then(() => { onChanged(); toast('success', t('Research restored.')) },
          (e: Error) => toast('error', t('Could not restore research: {message}', { message: e.message })))
      } })
    }, (e: Error) => toast('error', t('Could not move to Trash: {message}', { message: e.message })))
  }

  // PDFs into the Library, one by one; each line says what the server did with that file.
  async function upload(files: File[]) {
    if (locked || !files.length) return
    const added: string[] = []
    const already: string[] = []
    const noText: string[] = []
    const failed: string[] = []
    let last: LibraryView | undefined
    await write('upload', async () => {
      for (const file of files) {
        try {
          const answer = await libraryApi.upload(file)
          last = answer.library
          ;(answer.already_saved ? already : added).push(file.name)
          const entry = answer.library.entries.find(e => e.work_id === answer.work_id)
          if (!answer.already_saved && entry && entry.access_level !== 'pdf_available') noText.push(file.name)
        } catch (e) {
          failed.push(t('{file}: {message}', { file: file.name, message: errorText(e) }))
        }
      }
    }, () => last).catch(() => undefined)
    setResult({
      tone: failed.length ? (added.length || already.length ? 'warn' : 'bad') : 'ok',
      lines: [
        added.length ? t(added.length === 1 ? '{n} PDF saved to the Library; it is listed in All works.' : '{n} PDFs saved to the Library; they are listed in All works.', { n: added.length }) : '',
        noText.length ? t('No text layer could be read from {files}; reading depth there is not PDF text.', { files: noText.join(', ') }) : '',
        already.length ? t('Already saved in the Library, nothing added: {files}.', { files: already.join(', ') }) : '',
        ...failed.map(line => t('Not saved · {line}', { line })),
      ].filter(Boolean),
    })
  }

  async function importZotero(choice: ZoteroChoice) {
    if (locked) return
    try {
      const answer = await write('zotero', () => libraryImportsApi.zotero(choice.source, choice.key), a => a.library)
      setZoteroOpen(false)
      const z = answer.zotero_import
      setResult({
        tone: z.notes.length ? 'warn' : 'ok',
        lines: [
          t('“{name}”: {items} Zotero items read. {saved} saved to the Library and listed in All works; {already} were already saved.', { name: choice.name, items: z.items, saved: z.saved.length, already: z.already_saved.length }),
          t('{n} PDFs added. The titles, authors and years are Zotero’s, not checked against a provider.', { n: z.pdfs_added }),
          ...z.notes.map(note => `${note.title}: ${t(note.note, note.vars)}.`),
        ],
      })
    } catch (e) {
      setZoteroOpen(false)
      setResult({ tone: 'bad', lines: [t('Nothing was imported from Zotero: {message}', { message: errorText(e) })] })
    }
  }

  // A real file from the stored records of the picked works; the line counts the records in the file the server sent.
  async function exportBibliography(format: 'bibtex' | 'ris') {
    const works = pickedWorks.map(entry => entry.work_id)
    if (!works.length || locked) return
    setBusy('export')
    try {
      const { blob, filename } = await libraryApi.bibliography({ format, work_ids: works })
      const count = recordsIn(await blob.text(), format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      setResult({ tone: count === works.length ? 'ok' : 'warn', lines: [t('{file} saved with {n} records, one per chosen work ({chosen} chosen).', { file: filename, n: count, chosen: works.length })] })
    } catch (e) {
      setResult({ tone: 'bad', lines: [t('The bibliography could not be exported: {message}', { message: errorText(e) })] })
    } finally {
      setBusy(current => (current === 'export' ? null : current))
    }
  }

  // "Start evidence table" and "Ask about these works": a new research (scope `attached`) holding one stored version per
  // work, then its study table's column suggestions or its answer. Each line reports what the server did.
  async function startFromSelection(mode: Mode, works: string[], question: string, answer: ModelChoice, literature: ModelChoice) {
    const lines: string[] = []
    let open: Result['open']
    let tone: Result['tone'] = 'ok'
    try {
      await write('create', async () => {
        const created = await libraryApi.newResearchFromSet({
          question, intent: mode === 'table' ? 'table' : 'report', effort: 'standard',
          model_connection: answer.connection, requested_model: answer.model, reasoning_effort: answer.effort,
          literature_connection: literature.connection, literature_model: literature.model, literature_reasoning_effort: literature.effort,
          review_mode: 'default', review_connection: null, review_model: null, review_reasoning_effort: null, work_ids: works,
        })
        const id = created.research.id
        open = { id }
        lines.push(t('Research “{title}” created with {n} works from the Library.', { title: shortTitle(created.research.title || question), n: created.added_source_version_ids.length }))
        onChanged()
        if (mode === 'table') {
          const table = (await api.tables(id).catch(() => [])).find(item => item.title)
          if (!table) { tone = 'warn'; lines.push(t('No study table was made, so column suggestions did not start. Open the research to start a table.')); return }
          open = { id, tab: 'table' }
          lines.push(t('Its study table holds {n} rows.', { n: table.rows }))
          try {
            await api.suggestColumns(id, table.id, crypto.randomUUID())
            lines.push(t('Column suggestions started; the table panel shows them when they are ready.'))
          } catch (e) {
            tone = 'warn'
            lines.push(t('Column suggestions did not start: {message}', { message: errorText(e) }))
          }
        } else {
          try {
            await api.startRun(id, 'answer', crypto.randomUUID())
            lines.push(t('The answer started; the research page shows its steps.'))
          } catch (e) {
            tone = 'warn'
            lines.push(t('The answer did not start: {message}', { message: errorText(e) }))
          }
        }
      })
      setAsking(null)
      setPicked(new Set())
      setResult({ tone, lines, open })
    } catch (e) {
      setAsking(null)
      setResult({ tone: 'bad', lines: [t('No research was created: {message}', { message: errorText(e) })] })
    }
  }

  function startDrag(event: DragEvent, entry: LibraryEntry) {
    event.dataTransfer.effectAllowed = 'copy'
    event.dataTransfer.setData(WORK_TYPE, entry.work_id)
    event.dataTransfer.setData('text/plain', entry.doi ? `${entry.title} (doi:${entry.doi})` : entry.title)
    setDragging({ workId: entry.work_id, held: entry.researches.map(r => r.id) })
  }
  const endDrag = () => { setDragging(null); setDropTarget(null) }
  // A research in the left pane takes a dragged work it does not hold yet.
  const dropProps = (research: LibraryResearch) => ({
    onDragOver: (event: DragEvent) => {
      if (!dragging || dragging.held.includes(research.id) || locked) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
      if (dropTarget !== research.id) setDropTarget(research.id)
    },
    onDragLeave: (event: DragEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropTarget(current => (current === research.id ? null : current))
    },
    onDrop: (event: DragEvent) => {
      event.preventDefault()
      const workId = event.dataTransfer.getData(WORK_TYPE) || dragging?.workId
      endDrag()
      if (workId) void addWorks([workId], research)
    },
    'data-drop': !dragging ? undefined : dragging.held.includes(research.id) ? 'present' : dropTarget === research.id ? 'over' : 'ready',
  })

  const sheet = sheetTarget(work)

  if (view && !entries.length && !error) {
    return <section className="library-page lib-empty-page" ref={sectionRef}>
      <div className="empty lib-empty">
        <div>
          <LibraryBig size={16} aria-hidden />
          <h1 tabIndex={-1}>{t('No saved works yet')}</h1>
          <p>{t('The sources of every research land here. You can also upload PDFs or import a Zotero collection.')}</p>
          <div className="acts">
            <button type="button" className="btn-teal" disabled={locked} onClick={() => fileInput.current?.click()}><Upload size={16} aria-hidden />{t('Upload PDF')}</button>
            <button type="button" className="ghost" ref={zoteroButton} disabled={locked} onClick={() => setZoteroOpen(true)}>{t('Import from Zotero')}</button>
          </div>
          {result && <ResultNotice result={result} onOpen={target => onOpenResearch(target.id, target.tab)} onClose={() => setResult(null)} />}
        </div>
      </div>
      {fileInputEl()}
      <ZoteroDialog open={zoteroOpen} onOpenChange={setZoteroOpen} destination="library" busy={busy === 'zotero'} returnFocus={zoteroButton} onImport={choice => void importZotero(choice)} />
    </section>
  }

  function fileInputEl() {
    return <input ref={fileInput} type="file" accept="application/pdf,.pdf" multiple hidden
      onChange={event => { const files = [...(event.target.files ?? [])]; event.target.value = ''; void upload(files) }} />
  }

  const actions = <SelectionActions works={pickedWorks} researches={researches} project={project} locked={locked}
    onTable={() => setAsking({ mode: 'table', works: pickedWorks.map(e => e.work_id) })}
    onAsk={() => setAsking({ mode: 'ask', works: pickedWorks.map(e => e.work_id) })}
    onAdd={research => void addWorks(pickedWorks.map(e => e.work_id), research)}
    onExport={format => void exportBibliography(format)}
    onRemove={() => setPending({ research: project, works: pickedWorks.map(e => e.work_id) })} />

  return <section className="library-page" ref={sectionRef}>
    <div className="lib">
      <div className="lib-head">
        <h1 tabIndex={-1}><span>{t('Library')} /</span> <span className="lib-crumb" title={projectName}>{projectName}</span></h1>
        {project && <DropdownMenu>
          <DropdownMenuTrigger className="ib lib-project-menu" aria-label={t('Actions for {title}', { title: projectName })} title={t('More actions')}><Ellipsis size={16} aria-hidden /></DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-auto library-menu">
            <DropdownMenuItem onClick={() => onOpenResearch(project)}><FileText size={16} /><span className="library-tx">{t('Open research')}</span></DropdownMenuItem>
            <DropdownMenuItem variant="destructive" disabled={locked} onClick={() => { const r = researches.find(x => x.id === project); if (r) trashProject(r) }}>
              <Trash2 size={16} /><span className="library-tx">{t('Move to Trash')}</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>}
        <button type="button" className="ghost" ref={zoteroButton} disabled={locked} onClick={() => setZoteroOpen(true)}>{t('Import from Zotero')}</button>
        <button type="button" className="btn-teal" disabled={locked} aria-busy={busy === 'upload'} onClick={() => fileInput.current?.click()}><Upload size={16} aria-hidden />{t('Upload PDF')}</button>
      </div>
      <div className="lib-body">
        <div className="pane lib-left">
          <div className="cols-list" role="group" aria-label={t('Show works')}>
            <button type="button" className={project === null ? 'on' : undefined} aria-pressed={project === null} onClick={() => chooseProject(null)}>
              <span>{t('All works')}</span><em className="tnum">{view ? num(entries.length) : '–'}</em>
            </button>
            <h6>{t('Research')}</h6>
            {researches.map(research => <button type="button" key={research.id} data-research={research.id} className={project === research.id ? 'on' : undefined} aria-pressed={project === research.id}
              title={research.title} onClick={() => chooseProject(research.id)} {...dropProps(research)}>
              <span>{research.title}</span><em className="tnum">{num(heldBy(research.id))}</em>
            </button>)}
            {view && !researches.length && <p className="lib-none">{t('No research yet.')}</p>}
          </div>
        </div>

        <div className="pane lib-main">
          <div className="toolbar">
            <label className="search lib-search"><Search size={16} aria-hidden />
              <input ref={searchRef} type="search" value={query} placeholder={t('Title, author, venue or year')} aria-label={t('Search the library')}
                onChange={event => { setQuery(event.target.value); resetList() }} /></label>
            <DropdownMenu>
              <DropdownMenuTrigger className={`ghost lib-sort${sort !== 'added_new' ? ' tint' : ''}`} aria-label={t('Sort works')}><ArrowUpDown size={16} aria-hidden />{t(SORTS[sort])}</DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-auto library-menu">
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="lib-menu-h">{t('Sort')}</DropdownMenuLabel>
                  {(Object.keys(SORTS) as SortKey[]).map(key => <DropdownMenuItem key={key} onClick={() => chooseSort(key)}>
                    {sort === key ? <Check size={16} /> : <ArrowUpDown size={16} />}<span className="library-tx">{t(SORTS[key])}</span>
                  </DropdownMenuItem>)}
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger className={`ghost lib-pdf${pdf !== 'all' ? ' tint' : ''}`} aria-label={t('Filter works by PDF text')}><Filter size={16} aria-hidden />{t('PDF: {filter}', { filter: t(PDF_FILTERS[pdf]) })}</DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-auto library-menu">
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="lib-menu-h">PDF</DropdownMenuLabel>
                  {(['all', 'text', 'no_text'] as PdfFilter[]).map(key => <PdfItem key={key} value={key} current={pdf} count={inProject.filter(e => passesPdf(e, key)).length} onChoose={choosePdf} />)}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="lib-menu-h">{t('Reading depth')}</DropdownMenuLabel>
                  {(['abstract', 'metadata'] as PdfFilter[]).map(key => <PdfItem key={key} value={key} current={pdf} count={inProject.filter(e => passesPdf(e, key)).length} onChoose={choosePdf} />)}
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            <select className="lib-project-select" aria-label={t('Research')} value={project ?? ''} onChange={event => chooseProject(event.target.value || null)}>
              <option value="">{t('All works')} ({num(entries.length)})</option>
              {researches.map(r => <option key={r.id} value={r.id}>{r.title} ({num(heldBy(r.id))})</option>)}
            </select>
          </div>
          {error && <div className="notice bad lib-notice" role="alert"><X size={16} aria-hidden /><div className="nb">
            <span>{view ? t('Could not read the Library again: {message}. The list below may be out of date.', { message: error }) : t('Could not load the Library: {message}', { message: error })}</span>
            <div className="acts"><button type="button" className="ghost" onClick={() => { setError(''); load() }}>{t('Retry')}</button></div>
          </div></div>}
          {result && <ResultNotice result={result} onOpen={target => onOpenResearch(target.id, target.tab)} onClose={() => setResult(null)} />}
          <div className="tbl-wrap"><table className="lib-table">
            <thead><tr>
              <th className="cb"><input type="checkbox" aria-label={t('Select all {n} works listed', { n: shown.length })} disabled={!shown.length}
                checked={shown.length > 0 && shown.every(e => picked.has(e.work_id))}
                ref={box => { if (box) box.indeterminate = shown.some(e => picked.has(e.work_id)) && !shown.every(e => picked.has(e.work_id)) }}
                onChange={event => setPicked(event.target.checked ? new Set(shown.map(e => e.work_id)) : new Set())} /></th>
              <th scope="col">{t('Title')}</th><th scope="col">{t('Year')}</th><th scope="col">{t('Reading depth')}</th><th scope="col">{t('Research')}</th><th aria-label={t('Actions')} />
            </tr></thead>
            <tbody>
              {view === null && !error && <tr className="more-row"><td colSpan={6} role="status">{t('Loading Library…')}</td></tr>}
              {rows.map(entry => <Row key={entry.work_id} entry={entry} project={project} researches={researches} picked={picked.has(entry.work_id)} locked={locked}
                dragging={dragging?.workId === entry.work_id} onPick={() => togglePick(entry.work_id)} onOpen={() => openWork(entry)}
                onFocusTitle={() => { cursorRef.current = entry.work_id }} onDragStart={event => startDrag(event, entry)} onDragEnd={endDrag}
                onAdd={research => void addWorks([entry.work_id], research)} onOpenResearch={id => onOpenResearch(id, 'sources')}
                onCopyDoi={doi => void copyDoi(doi)} onRemove={() => setPending({ research: project, works: [entry.work_id] })} />)}
              {view !== null && !shown.length && <tr className="more-row lib-nomatch"><td colSpan={6}>
                {narrowed
                  ? <>{t(needle && pdf !== 'all' ? 'No works match “{q}” with {pdf}.' : needle ? 'No works match “{q}”.' : 'No works match with {pdf}.', { q: query.trim(), pdf: t(PDF_FILTERS[pdf]) })} <button type="button" className="link" onClick={() => { setQuery(''); choosePdf('all') }}>{t('Clear search and filter')}</button></>
                  : t('No work of this research is in the Library now.')}
              </td></tr>}
            </tbody>
          </table></div>
          {pages > 1 && <div className="lib-pager">
            <span className="lib-range tnum">{t('{first}–{last} of {total}', { first: currentPage * pageSize + 1, last: Math.min(shown.length, (currentPage + 1) * pageSize), total: num(shown.length) })}</span>
            <div className="lib-pages">
              <button type="button" onClick={() => setPage(currentPage - 1)} disabled={currentPage === 0} aria-label={t('Previous page')}><ChevronLeft size={16} aria-hidden /></button>
              {pagerItems(currentPage, pages).map((item, index) => item === 'gap'
                ? <span className="lib-page-gap" key={`gap-${index}`} aria-hidden>…</span>
                : <button type="button" key={item} onClick={() => setPage(item)} aria-current={item === currentPage ? 'page' : undefined}>{item + 1}</button>)}
              <button type="button" onClick={() => setPage(currentPage + 1)} disabled={currentPage >= pages - 1} aria-label={t('Next page')}><ChevronRight size={16} aria-hidden /></button>
              <DropdownMenu>
                <DropdownMenuTrigger className="ghost lib-page-size" aria-label={t('Rows per page')}>{t('{n} / page', { n: pageSize })}</DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-auto library-menu">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>{t('Rows per page')}</DropdownMenuLabel>
                    {PAGE_SIZES.map(size => <DropdownMenuItem key={size} onClick={() => choosePageSize(size)}>
                      {size === pageSize ? <Check size={16} /> : <span className="library-menu-gap" aria-hidden />}<span className="library-tx">{t('{n} / page', { n: size })}</span>
                    </DropdownMenuItem>)}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>}
          {picked.size > 0 && <div className="selbar lib-selbar" role="region" aria-label={t('Chosen works')}>
            <b aria-live="polite">{t('{n} chosen', { n: pickedWorks.length })}</b>
            <span className="spacer" />
            <SelectionActions bar works={pickedWorks} researches={researches} project={project} locked={locked}
              onTable={() => setAsking({ mode: 'table', works: pickedWorks.map(e => e.work_id) })}
              onAsk={() => setAsking({ mode: 'ask', works: pickedWorks.map(e => e.work_id) })}
              onAdd={research => void addWorks(pickedWorks.map(e => e.work_id), research)}
              onExport={format => void exportBibliography(format)}
              onRemove={() => setPending({ research: project, works: pickedWorks.map(e => e.work_id) })} />
            <button type="button" className="ghost" onClick={() => setPicked(new Set())}>{t('Clear')}</button>
          </div>}
          <ul className="lib-keys" aria-label={t('Keys')}>
            <li><kbd>/</kbd>{t('search')}</li>
            <li><kbd>↑</kbd><kbd>↓</kbd>{t('move between works')}</li>
            <li><kbd>x</kbd>{t('pick')}</li>
            <li><kbd>↵</kbd>{t('inspect')}</li>
          </ul>
        </div>

        <div className="pane lib-right">
          <div className="pane-h">{t('New from selection')}{pickedWorks.length ? ` · ${num(pickedWorks.length)}` : ''}</div>
          <div className="newsel">
            {actions}
            <p className="foot-note">{pickedWorks.length ? '' : t('Select works to start from them.')}</p>
            <div className="box lib-depth">
              <h5>{t('Reading depth, all works')}</h5>
              <div className="bar" role="img" aria-label={t('Reading depth across {total} works: {text} with PDF text, {abstract} abstract only, {metadata} metadata only.', { total: num(entries.length), text: num(depth.pdf_available), abstract: num(depth.abstract), metadata: num(depth.metadata) })}>
                {(['pdf_available', 'abstract', 'metadata'] as AccessLevel[]).map(level => depth[level] > 0 && <i key={level} className={`lib-d-${level}`} style={{ width: `${(depth[level] / Math.max(1, entries.length)) * 100}%` }} />)}
              </div>
              <div className="legend">
                <span><i className="lib-d-pdf_available" />{t('PDF {n}', { n: num(depth.pdf_available) })}</span>
                <span><i className="lib-d-abstract" />{t('Abstract {n}', { n: num(depth.abstract) })}</span>
                <span><i className="lib-d-metadata" />{t('Metadata {n}', { n: num(depth.metadata) })}</span>
              </div>
              <p className="lib-depth-note">{t('Depth is what DEIXIS holds for each work, not a claim about the work.')}
                {citationsReadAt && ` ${t('Citation counts come from OpenAlex; the newest was read on {date}.', { date: new Date(citationsReadAt).toLocaleDateString(uiLocale(), { dateStyle: 'medium' }) })}`}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    {fileInputEl()}
    {selected && sheet && <PassageSheet researchId={sheet.researchId} passageId={sheet.passageId} assetId={sheet.assetId} dark={dark} onClose={() => setSelected(null)} />}
    <ZoteroDialog open={zoteroOpen} onOpenChange={setZoteroOpen} destination="library" busy={busy === 'zotero'} returnFocus={zoteroButton} onImport={choice => void importZotero(choice)} />
    <NewResearchDialog request={asking} dark={dark} busy={busy === 'create'} count={asking?.works.length ?? 0}
      onClose={() => setAsking(null)} onStart={(question, answer, literature) => { if (asking) void startFromSelection(asking.mode, asking.works, question, answer, literature) }} />
    <ConfirmDialog open={pending !== null} dark={dark} neutral busy={busy === 'remove'}
      title={pending?.research ? t('Remove from this research?') : t('Remove from every research?')}
      description={pending?.research
        ? t('Every stored version leaves this research’s sources. The work stays in All works; its record, PDFs and the answers and cells that cite it stay. Undo in the notification brings it back.')
        : t('Every stored version leaves every research that holds the work. The work stays in All works; its record, PDFs and the answers and cells that cite it stay. Undo in the notification brings it back.')}
      context={pending ? (pending.works.length === 1 ? shortTitle(byWork.get(pending.works[0])?.title ?? '') : t('{n} works', { n: pending.works.length })) : undefined}
      confirmLabel={t('Remove')} cancelLabel={t('Cancel')}
      onConfirm={() => { if (pending) void removeWorks(pending) }}
      onOpenChange={open => { if (!open) setPending(null) }} />
  </section>
}

function PdfItem({ value, current, count, onChoose }: { value: PdfFilter; current: PdfFilter; count: number; onChoose: (value: PdfFilter) => void }) {
  return <DropdownMenuItem onClick={() => onChoose(value)}>
    {current === value ? <Check size={16} /> : <FileText size={16} />}<span className="library-tx">{t(PDF_FILTERS[value])}</span>
    <span className="library-menu-hint tnum">{num(count)}</span>
  </DropdownMenuItem>
}

function ResultNotice({ result, onOpen, onClose }: { result: Result; onOpen: (target: NonNullable<Result['open']>) => void; onClose: () => void }) {
  return <div className={`notice lib-result${result.tone === 'ok' ? ' info' : ` ${result.tone}`}`} role="status">
    {result.tone === 'ok' ? <Check size={16} aria-hidden /> : <X size={16} aria-hidden />}
    <div className="nb">
      {result.lines.map((line, i) => <span key={i}>{line}</span>)}
      {result.open && <div className="acts"><button type="button" className="ghost" onClick={() => onOpen(result.open!)}>{t('Open research')}</button></div>}
    </div>
    <button type="button" className="ib lib-result-close" aria-label={t('Close')} onClick={onClose}><X size={16} aria-hidden /></button>
  </div>
}

// The four "New from selection" actions (mockup `.newsel`), and removal from the research shown (or from every research in
// All works), a live action the mockup has no place for. In the pane each is a row with its icon on the right; in the bar
// under the table (below 1100px) a ghost button.
function SelectionActions({ works, researches, project, locked, bar = false, onTable, onAsk, onAdd, onExport, onRemove }: {
  works: LibraryEntry[]; researches: LibraryResearch[]; project: string | null; locked: boolean; bar?: boolean
  onTable: () => void; onAsk: () => void; onAdd: (research: LibraryResearch) => void; onExport: (format: 'bibtex' | 'ris') => void; onRemove: () => void
}) {
  const none = !works.length
  const off = none || locked
  const cls = bar ? 'ghost' : undefined
  const item = (label: string, icon: ReactNode) => bar ? <>{icon}{t(label)}</> : <>{t(label)}{icon}</>
  // What removal would take out: the works the shown research holds, or in All works every work some research holds.
  const removable = works.filter(entry => (project ? entry.researches.some(r => r.id === project) : entry.researches.length > 0)).length
  return <>
    <button type="button" className={cls} disabled={off} onClick={onTable}>{item('Start evidence table', <Table2 size={16} aria-hidden />)}</button>
    <button type="button" className={cls} disabled={off} onClick={onAsk}>{item('Ask about these works', <MessageSquare size={16} aria-hidden />)}</button>
    <DropdownMenu>
      <DropdownMenuTrigger disabled={off} render={<button type="button" className={cls} />}>{item('Add to a research', <Folder size={16} aria-hidden />)}</DropdownMenuTrigger>
      <DropdownMenuContent align={bar ? 'start' : 'end'} className="w-auto library-menu">
        <DropdownMenuGroup>
        <DropdownMenuLabel className="lib-menu-h">{t('Add to a research')}</DropdownMenuLabel>
        {!researches.length && <p className="library-menu-note">{t('No research yet.')}</p>}
        {researches.map(research => {
          const held = works.filter(entry => entry.researches.some(r => r.id === research.id)).length
          const all = held === works.length && held > 0
          return <DropdownMenuItem key={research.id} data-research={research.id} disabled={all || locked} onClick={() => onAdd(research)}>
            {all ? <Check size={16} /> : <Folder size={16} />}
            <span className="library-tx">{research.title}{all ? <small>{t('Already in it')}</small> : held ? <small>{t('{n} of {m} already in it', { n: held, m: works.length })}</small> : null}</span>
          </DropdownMenuItem>
        })}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
    <DropdownMenu>
      <DropdownMenuTrigger disabled={off} render={<button type="button" className={cls} />}>{item('Export .bib / .ris', <Download size={16} aria-hidden />)}</DropdownMenuTrigger>
      <DropdownMenuContent align={bar ? 'start' : 'end'} className="w-auto library-menu">
        <DropdownMenuItem onClick={() => onExport('bibtex')}><Download size={16} /><span className="library-tx">{t('BibTeX (.bib)')}</span></DropdownMenuItem>
        <DropdownMenuItem onClick={() => onExport('ris')}><Download size={16} /><span className="library-tx">{t('RIS (.ris)')}</span></DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    {removable > 0 && <button type="button" className={`${cls ?? ''} lib-remove`.trim()} disabled={locked} onClick={onRemove}>
      {item(project ? 'Remove from this research' : 'Remove from every research', <Trash2 size={16} aria-hidden />)}</button>}
  </>
}

function Row({ entry, project, researches, picked, locked, dragging, onPick, onOpen, onFocusTitle, onDragStart, onDragEnd, onAdd, onOpenResearch, onCopyDoi, onRemove }: {
  entry: LibraryEntry; project: string | null; researches: LibraryResearch[]; picked: boolean; locked: boolean; dragging: boolean
  onPick: () => void; onOpen: () => void; onFocusTitle: () => void; onDragStart: (event: DragEvent) => void; onDragEnd: () => void
  onAdd: (research: LibraryResearch) => void; onOpenResearch: (id: string) => void; onCopyDoi: (doi: string) => void; onRemove: () => void
}) {
  const owner = project ?? entry.researches[0]?.id ?? null
  const removable = project ? entry.researches.some(r => r.id === project) : entry.researches.length > 0
  return <tr className={[picked ? 'sel' : '', dragging ? 'is-dragging' : ''].filter(Boolean).join(' ') || undefined} draggable onDragStart={onDragStart} onDragEnd={onDragEnd}>
    <td className="cb"><input type="checkbox" checked={picked} onChange={onPick} aria-label={t('Select “{title}”', { title: shortTitle(entry.title) })} /></td>
    <td className="lib-title-cell">
      <span className="lib-title-line"><SourceKey value={entry.source_key} className="lib-key" /><button type="button" className="src-t library-title" onClick={onOpen} onFocus={onFocusTitle}
        title={t('Open the stored passages for this work')}>{entry.title}</button></span>
      <div className="src-m">{authorsText(entry.authors)}{entry.cited_by_count !== null && ` · ${t(entry.cited_by_count === 1 ? '{n} citation' : '{n} citations', { n: num(entry.cited_by_count) })}`}</div>
      {entry.versions.length > 1 && <div className="pills">{entry.versions.map(version => <span key={version.source_version_id} className="pill">
        {versionText(version.version_label)} · {t(ACCESS_LABELS[version.access_level])}</span>)}</div>}
    </td>
    <td className="tnum">{entry.year ?? '—'}</td>
    <td><span className="pill lib-depth-pill"><i className={`rd lib-d-${entry.access_level}`} aria-hidden />{t(ACCESS_LABELS[entry.access_level])}</span></td>
    <td className="lib-research-cell">{entry.researches.length
      ? <><span className="lib-first">{entry.researches[0].title}</span>{entry.researches.length > 1 && <span className="lib-more">{t('+{n} more', { n: entry.researches.length - 1 })}</span>}</>
      : <span className="lib-more">{t('None')}</span>}</td>
    <td className="lib-act">
      <DropdownMenu>
        <DropdownMenuTrigger className="ib" aria-label={t('More for “{title}”', { title: shortTitle(entry.title) })} title={t('More actions')}><Ellipsis size={16} aria-hidden /></DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-auto library-menu">
          <DropdownMenuGroup>
          <DropdownMenuLabel className="lib-menu-h">{t('Add to a research')}</DropdownMenuLabel>
          {!researches.length && <p className="library-menu-note">{t('No research yet.')}</p>}
          {researches.map(research => {
            const held = entry.researches.some(r => r.id === research.id)
            return <DropdownMenuItem key={research.id} data-research={research.id} disabled={held || locked} onClick={() => onAdd(research)}>
              {held ? <Check size={16} /> : <Folder size={16} />}<span className="library-tx">{research.title}{held && <small>{t('Already in it')}</small>}</span>
            </DropdownMenuItem>
          })}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={!owner} onClick={() => { if (owner) onOpenResearch(owner) }}>
            <FileText size={16} /><span className="library-tx">{t('Open in research')}{!owner && <small>{t('No research holds it')}</small>}</span>
          </DropdownMenuItem>
          <DropdownMenuItem disabled={!entry.doi} onClick={() => { if (entry.doi) onCopyDoi(entry.doi) }}>
            <Link2 size={16} /><span className="library-tx">{t('Copy DOI')}{!entry.doi && <small>{t('no DOI stored')}</small>}</span>
          </DropdownMenuItem>
          {removable && <DropdownMenuItem variant="destructive" disabled={locked} onClick={onRemove}>
            <X size={16} /><span className="library-tx">{project ? t('Remove from this research') : t('Remove from every research')}<small>{t('Stays in All works')}</small></span>
          </DropdownMenuItem>}
        </DropdownMenuContent>
      </DropdownMenu>
    </td>
  </tr>
}

// "Start evidence table" / "Ask about these works": the question the new research asks, and the models it runs with,
// named before anything starts. Nothing is sent until Start.
function NewResearchDialog({ request, dark, busy, count, onClose, onStart }: {
  request: { mode: Mode; works: string[] } | null; dark: boolean; busy: boolean; count: number
  onClose: () => void; onStart: (question: string, answer: ModelChoice, literature: ModelChoice) => void
}) {
  const [question, setQuestion] = useState('')
  const [models, setModels] = useState<{ answer: ModelChoice | null; literature: ModelChoice | null } | null>(null)
  const [failed, setFailed] = useState('')
  const open = request !== null
  const mode = request?.mode ?? 'ask'
  useEffect(() => {
    if (!open) return
    let live = true
    setQuestion('')
    setModels(null)
    setFailed('')
    Promise.all([api.connections(), api.settings().catch(() => null)]).then(([connections, saved]) => {
      if (!live) return
      const list = connectionModels(connections)
      const defaults = saved as Record<ModelRole, RoleModelSetting> | null
      setModels({ answer: startModel(list, defaults?.answer), literature: startModel(list, defaults?.literature) })
    }, (e: Error) => { if (live) setFailed(e.message) })
    return () => { live = false }
  }, [open])
  const ready = Boolean(models?.answer && models.literature)
  const line = (role: string, choice: ModelChoice | null) => choice
    ? t(choice.fromSettings ? '{role}: {model} (the default in Settings)' : '{role}: {model} (the connection’s default; Settings has none)', { role: t(role), model: choice.name })
    : t('{role}: no model is listed by any connection.', { role: t(role) })
  return <ConfirmDialog open={open} dark={dark} neutral busy={busy} confirmDisabled={!ready || question.trim().length < 3}
    title={t(mode === 'table' ? 'Start evidence table' : 'Ask about these works')}
    description={t(mode === 'table'
      ? 'A new research holds the {n} chosen works as its only sources, with a study table of them. Column suggestions start once it is made.'
      : 'A new research holds the {n} chosen works as its only sources and answers your question from them. No search is run.', { n: count })}
    confirmLabel={t('Start')} cancelLabel={t('Cancel')}
    onConfirm={() => { if (models?.answer && models.literature) onStart(question.trim(), models.answer, models.literature) }}
    onOpenChange={next => { if (!next) onClose() }}>
    <label className="lib-question">{t(mode === 'table' ? 'What should the table compare?' : 'Your question')}
      <textarea className="field" rows={3} maxLength={4000} value={question} onChange={event => setQuestion(event.target.value)} /></label>
    {failed ? <p className="lib-models" role="alert">{t('Could not read the model connections: {message}', { message: failed })}</p>
      : !models ? <p className="lib-models" role="status">{t('Reading the model connections…')}</p>
      : <p className="lib-models">{line('Answer model', models.answer)}<br />{line('Literature model', models.literature)}</p>}
  </ConfirmDialog>
}

function sheetTarget(work: LibraryWork | null) {
  const withPdf = work?.versions.find(version => version.research_id && version.asset)
  if (withPdf) return { researchId: withPdf.research_id as string, assetId: (withPdf.asset as { id: string }).id, passageId: null }
  const withAbstract = work?.versions.find(version => version.abstract_passage_id && (version.research_id ?? version.removed_research_id))
  if (withAbstract) return { researchId: (withAbstract.research_id ?? withAbstract.removed_research_id) as string, assetId: null, passageId: withAbstract.abstract_passage_id }
  return null
}
