import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Check, FileText, Maximize, Plus, Search, TriangleAlert, ZoomIn, ZoomOut } from 'lucide-react'
import { api, ApiError, type CitationMap as MapData, type CitationMapPlan, type Run } from '../api'
import { ConnectionIcon } from '../connectionIcons'
import { Notice } from '../Notice'
import { useToast } from '../Toast'
import { t, uiLocale } from '../i18n'
import { usePanels } from '../research/usePanelStack'
import '../research/kit.css'
import './citation-map.css'

// The citation map panel (D42, owner-approved mockup .local/design/citation-map-mockup): the research's works and the
// outside works their stored OpenAlex reference lists name, drawn as a year timeline or a deterministic force layout,
// a detail side for the chosen work, the research's core and the often-cited outside works. Links come from stored
// reference lists only; no model is called. Reading missing lists is a run the person starts from the plan row.

type Kind = 'included' | 'pending' | 'excluded' | 'outside'
const KINDS: Kind[] = ['included', 'pending', 'excluded', 'outside']
const KIND_LABELS: Record<Kind, string> = { included: 'Included', pending: 'Undecided', excluded: 'Excluded', outside: 'Not in this research' }
// A large research shows its included works, its most-cited undecided works and the outside works; "Show all" adds the rest.
const PENDING_SHOWN = 30
const ZOOM_MIN = 0.5
const ZOOM_MAX = 8
type Zoom = { k: number; x: number; y: number }
const WHOLE_MAP: Zoom = { k: 1, x: 0, y: 0 }

// Scale by `factor` around point `p` (in the drawing's own units), so the point under the pointer stays put.
function zoomAt(z: Zoom, p: { x: number; y: number }, factor: number): Zoom {
  const k = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z.k * factor))
  return { k, x: p.x - (p.x - z.x) * (k / z.k), y: p.y - (p.y - z.y) * (k / z.k) }
}

function svgPoint(el: SVGSVGElement, clientX: number, clientY: number) {
  const m = el.getScreenCTM()
  if (!m) return { x: 0, y: 0 }
  const p = new DOMPoint(clientX, clientY).matrixTransform(m.inverse())
  return { x: p.x, y: p.y }
}

// An outside work known only by its OpenAlex id: the map run has not asked for its record yet, or OpenAlex sent none.
function titleOf(n: MapNode, describable: boolean): string {
  return n.title ?? t(describable ? 'Title not fetched yet' : 'OpenAlex sent no record for this id')
}
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const BUDGET_STOP = 'openalex_budget_exhausted'
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const plural = (n: number, one: string, many: string, vars: Record<string, string | number> = {}) => t(n === 1 ? one : many, { n, ...vars })
// The plan row joins clauses that may start in lower case; the row itself starts as a sentence.
const sentence = (text: string) => text.charAt(0).toLocaleUpperCase(uiLocale()) + text.slice(1)

type MapNode = {
  key: string; kind: Kind; title: string | null; short: string; authors: string[]; year: number | null; venue: string | null
  doi: string | null; citedBy: number | null; sourceVersionId: string | null; openalexId: string | null
  // In-research works only: whether any version's reference list was read. An outside work's list is never read.
  read: boolean; removed: boolean
}
type Graph = { nodes: MapNode[]; byKey: Map<string, MapNode>; links: [string, string][]; indeg: Map<string, number>; outdeg: Map<string, number> }

const outsideKey = (openalexId: string) => `out:${openalexId}`
function shortName(authorsShort: string, title: string | null, fallback: string) {
  if (authorsShort) return authorsShort
  if (title) return title.length > 22 ? `${title.slice(0, 21)}…` : title
  return fallback
}
const nameOf = (n: MapNode) => (n.year ? `${n.short} ${n.year}` : n.short)

function toGraph(map: MapData): Graph {
  const nodes: MapNode[] = map.nodes.map(n => ({
    key: n.work_id, kind: n.state, title: n.title, short: shortName(n.authors_short, n.title, n.openalex_ids[0] ?? ''), authors: n.authors,
    year: n.year, venue: n.venue, doi: n.doi, citedBy: n.cited_by_count, sourceVersionId: n.source_version_id, openalexId: n.openalex_ids[0] ?? null,
    read: n.references_read, removed: false,
  }))
  for (const o of map.outside) nodes.push({
    key: outsideKey(o.openalex_id), kind: 'outside', title: o.title, short: shortName(o.authors_short, o.title, o.openalex_id), authors: o.authors,
    year: o.year, venue: o.venue, doi: o.doi, citedBy: o.cited_by_count, sourceVersionId: o.source_version_id, openalexId: o.openalex_id,
    read: true, removed: o.removed_from_research,
  })
  const links: [string, string][] = [...map.edges.map(e => [e.from, e.to] as [string, string]),
    ...map.outside.flatMap(o => o.cited_by.map(w => [w, outsideKey(o.openalex_id)] as [string, string]))]
  const indeg = new Map<string, number>(), outdeg = new Map<string, number>()
  for (const [a, b] of links) { outdeg.set(a, (outdeg.get(a) ?? 0) + 1); indeg.set(b, (indeg.get(b) ?? 0) + 1) }
  return { nodes, byKey: new Map(nodes.map(n => [n.key, n])), links, indeg, outdeg }
}

// ---- layouts ---------------------------------------------------------------------------------------------------------
type Layout = { pos: Map<string, { x: number; y: number; col?: number }>; W: number; H: number; axis: { label: string; x: number }[]; dense: boolean }
const L = 56, R = 56, T = 40, B = 70

// Timeline: one column per publication year (works without a year last), stacked by how many works here cite them.
function layoutTime(nodes: MapNode[], indeg: Map<string, number>, minW = 920, minH = 460): Layout {
  const years = [...new Set(nodes.map(n => n.year))].sort((a, b) => (a === null ? 1 : b === null ? -1 : a - b))
  const step = years.length > 1 ? Math.max((minW - L - R) / (years.length - 1), 72) : 0
  const W = years.length > 1 ? L + R + step * (years.length - 1) : minW
  const columns = years.map(y => nodes.filter(n => n.year === y)
    .sort((a, b) => (indeg.get(b.key) ?? 0) - (indeg.get(a.key) ?? 0) || (a.title ?? '').localeCompare(b.title ?? '') || a.key.localeCompare(b.key)))
  const tallest = Math.max(1, ...columns.map(c => c.length))
  const gap = tallest > 1 ? Math.min(82, Math.max(26, 380 / (tallest - 1))) : 82
  const H = Math.max(minH, T + B + (tallest - 1) * gap + 60)
  const mid = T + (H - T - B) / 2
  const pos = new Map<string, { x: number; y: number; col?: number }>()
  const axis: Layout['axis'] = []
  columns.forEach((column, i) => {
    const x = years.length > 1 ? L + i * step : W / 2
    axis.push({ label: years[i] === null ? t('No year') : String(years[i]), x })
    column.forEach((n, j) => pos.set(n.key, { x, y: mid + (j - (column.length - 1) / 2) * gap, col: i }))
  })
  return { pos, W, H, axis, dense: gap < 40 }
}

// "Network": a deterministic force layout seeded from the timeline, with fewer iterations as the map grows.
function layoutNet(nodes: MapNode[], links: [string, string][]): Layout {
  const n = nodes.length
  const W = Math.max(920, Math.round(Math.sqrt(n) * 130)), H = Math.max(460, Math.round(Math.sqrt(n) * 75))
  const seed = layoutTime(nodes, new Map(), W, H).pos
  const index = new Map(nodes.map((node, i) => [node.key, i]))
  const x = new Float64Array(n), y = new Float64Array(n), vx = new Float64Array(n), vy = new Float64Array(n)
  nodes.forEach((node, i) => { const p = seed.get(node.key)!; x[i] = p.x; y[i] = Math.min(H - 50, Math.max(30, p.y)) })
  const pairs = links.flatMap(([a, b]) => { const i = index.get(a), j = index.get(b); return i === undefined || j === undefined ? [] : [[i, j]] })
  const iterations = n <= 150 ? 320 : Math.max(60, Math.round(320 * (150 / n) ** 2))
  for (let it = 0; it < iterations; it++) {
    for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) {
      const dx = x[a] - x[b], dy = y[a] - y[b], d2 = dx * dx + dy * dy || 1, f = 2600 / d2, d = Math.sqrt(d2)
      vx[a] += f * dx / d; vy[a] += f * dy / d; vx[b] -= f * dx / d; vy[b] -= f * dy / d
    }
    for (const [a, b] of pairs) {
      const dx = x[b] - x[a], dy = y[b] - y[a], d = Math.hypot(dx, dy) || 1, f = (d - 120) * 0.012
      vx[a] += f * dx / d; vy[a] += f * dy / d; vx[b] -= f * dx / d; vy[b] -= f * dy / d
    }
    for (let i = 0; i < n; i++) {
      vx[i] += (W / 2 - x[i]) * 0.004; vy[i] += (H / 2 - y[i]) * 0.006
      x[i] += vx[i] * 0.5; y[i] += vy[i] * 0.5; vx[i] *= 0.6; vy[i] *= 0.6
      x[i] = Math.max(50, Math.min(W - 50, x[i])); y[i] = Math.max(30, Math.min(H - 50, y[i]))
    }
  }
  return { pos: new Map(nodes.map((node, i) => [node.key, { x: x[i], y: y[i] }])), W, H, axis: [], dense: n > 60 }
}

const radius = (indeg: number) => Math.min(26, 6 + Math.sqrt(indeg) * 3.2)

export function CitationMap({ researchId, eventCursor, run, onOpenSource, onChanged }: {
  researchId: string; eventCursor: number; run: Run | undefined
  onOpenSource: (sourceVersionId: string) => void; onChanged: () => Promise<unknown>
}) {
  const toast = useToast()
  const [map, setMap] = useState<MapData | null>(null)
  const [plan, setPlan] = useState<CitationMapPlan | null>(null)
  const [error, setError] = useState('')
  const [layout, setLayout] = useState<'time' | 'net'>('time')
  const [show, setShow] = useState<Record<Kind, boolean>>({ included: true, pending: true, excluded: true, outside: true })
  const [allPending, setAllPending] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  // Outside works added from this panel, shown as "In candidates" until the map read after the addition lists them as sources.
  const [added, setAdded] = useState<ReadonlySet<string>>(new Set())
  const [adding, setAdding] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const generation = useRef(0)
  const [zoom, setZoom] = useState<Zoom>(WHOLE_MAP)
  const [panning, setPanning] = useState(false)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const pan = useRef<{ px: number; py: number; x: number; y: number } | null>(null)
  const markerId = useId().replace(/[^a-zA-Z0-9]/g, '')

  // The mockup opens the map as a full-width panel; Exit full width still narrows it.
  const setWide = usePanels()?.setWide
  useEffect(() => { setWide?.(true) }, [setWide])

  // The map and the plan are read when the panel opens and again on every recorded event (a run step, a selection).
  const reload = useCallback(async () => {
    const request = ++generation.current
    const [fresh, nextPlan] = await Promise.allSettled([api.citationMap(researchId), api.prepareCitationMap(researchId)])
    if (request !== generation.current) return
    if (fresh.status === 'fulfilled') { setMap(fresh.value); setError('') } else setError(errorText(fresh.reason))
    setPlan(nextPlan.status === 'fulfilled' ? nextPlan.value : null)
  }, [researchId])
  const runStatus = run?.status
  useEffect(() => { void reload() }, [reload, eventCursor, run?.id, runStatus])
  useEffect(() => () => clearTimeout(hoverTimer.current), [])

  const graph = useMemo(() => (map ? toGraph(map) : null), [map])
  const pendingRanked = useMemo(() => (graph ? graph.nodes.filter(n => n.kind === 'pending')
    .sort((a, b) => (graph.indeg.get(b.key) ?? 0) - (graph.indeg.get(a.key) ?? 0) || (a.title ?? '').localeCompare(b.title ?? '')) : []), [graph])
  const topPending = useMemo(() => new Set(pendingRanked.slice(0, PENDING_SHOWN).map(n => n.key)), [pendingRanked])
  // The research's core: its included and undecided works the most other works here cite.
  const core = useMemo(() => (graph ? graph.nodes.filter(n => (n.kind === 'included' || n.kind === 'pending') && (graph.indeg.get(n.key) ?? 0) > 0)
    .sort((a, b) => (graph.indeg.get(b.key) ?? 0) - (graph.indeg.get(a.key) ?? 0) || (a.title ?? '').localeCompare(b.title ?? '')).slice(0, 5) : []), [graph])
  const visible = useMemo(() => (graph ? graph.nodes.filter(n => show[n.kind]
    && (n.kind !== 'pending' || allPending || topPending.has(n.key) || n.key === sel)) : []), [graph, show, allPending, topPending, sel])
  const visibleKey = visible.map(n => n.key).join('|')
  const visibleSet = useMemo(() => new Set(visible.map(n => n.key)), [visible])
  // The layout depends only on which works show, never on the selection or the pointer.
  const drawn = useMemo(() => {
    if (!graph || !visible.length) return null
    const links = graph.links.filter(([a, b]) => visibleSet.has(a) && visibleSet.has(b))
    const lay = layout === 'time' ? layoutTime(visible, graph.indeg) : layoutNet(visible, links)
    return { links, layout: lay }
    // visibleKey stands for `visible` and `visibleSet`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, visibleKey, layout])
  // A zoom spreads the works apart but keeps circles and names at their size, so each link's curve is drawn again for
  // the zoom: from the citing work's left side to the cited work's right side on the timeline, a slight arc ending at the
  // cited work's rim in the network.
  const paths = useMemo(() => {
    if (!graph || !drawn) return []
    const { links, layout: lay } = drawn
    const r = (key: string) => radius(graph.indeg.get(key) ?? 0) / zoom.k
    return links.map(([s, d]) => {
      const a = lay.pos.get(s)!, b = lay.pos.get(d)!
      const rb = r(d) + 3, dx = b.x - a.x, dy = b.y - a.y, dist = Math.hypot(dx, dy) || 1
      if (layout === 'time') {
        const k = Math.max(30, Math.abs(dx) * 0.45), ex = b.x + rb
        return `M${a.x - r(s)},${a.y} C${a.x - k},${a.y} ${ex + k},${b.y} ${ex},${b.y}`
      }
      const ex = b.x - dx / dist * rb, ey = b.y - dy / dist * rb, mx = (a.x + ex) / 2 - dy * 0.12, my = (a.y + ey) / 2 + dx * 0.12
      return `M${a.x},${a.y} Q${mx},${my} ${ex},${ey}`
    })
  }, [graph, drawn, layout, zoom.k])
  // A new drawing starts at the whole map.
  useEffect(() => { setZoom(WHOLE_MAP) }, [drawn])
  // ⌘/Ctrl + wheel, and a trackpad pinch (which arrives as a ctrl wheel), zoom around the pointer; a plain wheel still
  // scrolls the page. The listener is not passive so the browser's own page zoom does not run as well.
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const p = svgPoint(el, e.clientX, e.clientY)
      setZoom(z => zoomAt(z, p, Math.exp(-e.deltaY * 0.01)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [drawn])

  if (error && !map) return <div className="mk citemap"><Notice tone="error">{error}<button type="button" className="ghost" onClick={() => void reload()}>{t('Retry')}</button></Notice></div>
  if (!map || !graph) return <div className="mk citemap"><p role="status">{t('Loading the citation map…')}</p></div>

  const selected = sel && visibleSet.has(sel) ? sel : (core.find(n => visibleSet.has(n.key)) ?? visible[0])?.key ?? null
  const focus = hover ?? selected
  const neighbours = new Set<string>(focus ? [focus] : [])
  if (focus) for (const [a, b] of drawn?.links ?? []) { if (a === focus) neighbours.add(b); if (b === focus) neighbours.add(a) }
  const needle = query.trim().toLocaleLowerCase(uiLocale())
  const hits = new Set(needle ? visible.filter(n => [n.short, n.year ?? '', n.title ?? '', n.openalexId ?? '', ...n.authors].join(' ').toLocaleLowerCase(uiLocale()).includes(needle)).map(n => n.key) : [])
  const indeg = (key: string) => graph.indeg.get(key) ?? 0

  const running = Boolean(run && ACTIVE.has(run.status))
  const paused = run?.status === 'paused' ? run : null
  const budgetStop = paused?.pause_reason === BUDGET_STOP
  const resetAt = budgetStop ? (paused?.error as { reset_at?: string } | null)?.reset_at ?? null : null
  const single = map.nodes.length === 1
  // Outside works still without a record can be described by the next map run; otherwise OpenAlex already sent none.
  const describable = (plan?.outside_to_describe ?? 0) > 0
  const counts: Record<Kind, number> = { included: 0, pending: 0, excluded: 0, outside: 0 }
  graph.nodes.forEach(n => counts[n.kind]++)
  const outsideRanked = graph.nodes.filter(n => n.kind === 'outside')
  const maxIn = Math.max(1, ...graph.nodes.map(n => indeg(n.key)))
  const noOpenAlex = map.nodes.length > 0 && map.nodes.every(n => !n.openalex_ids.length) && !map.outside.length && (!plan || plan.requests === 0)

  const select = (key: string) => { setSel(key); setHover(null) }
  const hoverTo = (key: string | null) => {
    clearTimeout(hoverTimer.current)
    hoverTimer.current = setTimeout(() => setHover(key), key ? 60 : 120)
  }
  const start = async () => {
    setStarting(true)
    try { await api.runCitationMap(researchId); await onChanged() }
    catch (e) { toast(e instanceof ApiError && e.status === 409 ? 'warning' : 'error', errorText(e)); await reload() }
    finally { setStarting(false) }
  }
  const resume = async () => {
    if (!paused) return
    setStarting(true)
    try { await api.controlRun(paused.id, 'resume'); await onChanged() }
    catch (e) { toast('error', errorText(e)) }
    finally { setStarting(false) }
  }
  const undo = async (ids: string[], openalexId: string) => {
    try {
      await api.removeSources(researchId, ids)
      setAdded(previous => { const next = new Set(previous); next.delete(openalexId); return next })
      setSel(outsideKey(openalexId))
      toast('success', t('Source removed from this research.'))
      await reload(); await onChanged()
    } catch (e) { toast('error', errorText(e)) }
  }
  const add = async (node: MapNode) => {
    const openalexId = node.openalexId
    if (!openalexId || adding) return
    setAdding(openalexId)
    try {
      const result = await api.addOutsideWork(researchId, openalexId)
      setAdded(previous => new Set(previous).add(openalexId))
      setSel(result.work_id)
      toast('success', t(result.restored ? '{name} was restored to this research' : '{name} was added to the candidates', { name: nameOf(node) }),
        { label: t('Undo'), run: () => { void undo(result.changed_source_version_ids, openalexId) } })
      await reload(); await onChanged()
    } catch (e) {
      const code = e instanceof ApiError ? e.code : null
      if (code === 'outside_work_not_described') toast('warning', t('This work has no stored record yet. Run “Read reference lists” first, then add it.'))
      else if (code === 'already_in_research') { toast('warning', t('This work is already a source of this research.')); await reload() }
      else if (code === 'ambiguous_outside_work') toast('warning', t('More than one work in your library carries this OpenAlex id, so it is not known which one to add. Nothing was added.'))
      else toast('error', errorText(e))
    } finally { setAdding(null) }
  }

  // ---- the plan row, the quota band, the summary ------------------------------------------------------------------
  const planParts = plan ? [
    plan.works_to_resolve > 0 && plural(plan.works_to_resolve, '{n} source is looked up in OpenAlex', '{n} sources are looked up in OpenAlex'),
    plan.sources_to_read > 0 && plural(plan.sources_to_read, 'the reference list of {n} source was not read', 'the reference lists of {n} sources were not read'),
    plan.outside_to_describe > 0 && plural(plan.outside_to_describe, '{n} work outside this research has no title yet', '{n} works outside this research have no title yet'),
    plan.requests > 0 && plural(plan.requests, '{n} OpenAlex request', '{n} OpenAlex requests'),
  ].filter((part): part is string => Boolean(part)) : []
  const noDoi = plan && plan.unresolvable_without_doi > 0
    ? plural(plan.unresolvable_without_doi, '{n} uploaded PDF has no DOI and cannot be matched', '{n} uploaded PDFs have no DOI and cannot be matched') : null
  const planRow = running
    ? <div className="cm-plan" role="status"><span className="spin" aria-hidden /><p>{t('Reading reference lists…')}</p></div>
    : paused && !budgetStop
      ? <div className="cm-plan"><p>{t('Reference list reading is paused.')}</p><button type="button" className="ghost" disabled={starting} onClick={() => void resume()}>{t('Resume')}</button></div>
      : !paused && (planParts.length || noDoi)
        ? <div className="cm-plan"><p className="tnum">{sentence([...planParts, noDoi].filter(Boolean).join(' · '))}{planParts.length > 0 && <>{' · '}<span className="cm-plan-free">{t('no model call')}</span></>}</p>
          {plan && plan.requests > 0 && <button type="button" className="btn-pri" disabled={starting} onClick={() => void start()}>{t('Read reference lists')}</button>}</div>
        : null
  const budgetLost = plan && plan.sources_to_read > 0
    ? plural(plan.sources_to_read, 'The reference list of {n} source could not be read; links from it are missing from the map. Its ring is dotted.', 'The reference lists of {n} sources could not be read; links from them are missing from the map. Their rings are dotted.')
    : plan && plan.outside_to_describe > 0 ? plural(plan.outside_to_describe, '{n} work outside this research could not be described.', '{n} works outside this research could not be described.') : ''
  const resetDate = resetAt ? new Date(resetAt) : null
  const banner = budgetStop && <div className="cm-banner" role="status"><TriangleAlert size={16} aria-hidden />
    <p><b>{t('OpenAlex’s daily quota is used up.')}</b> {budgetLost}
      {resetDate && !Number.isNaN(resetDate.getTime()) && <> {t('The quota renews around {time}.', { time: resetDate.toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) })}</>}</p>
    <button type="button" className="ghost" disabled={starting} onClick={() => void resume()}>{t('Retry')}</button></div>
  const linkCount = graph.links.length
  const summary = single
    ? <><div className="cm-sum"><h2>{t('Source citation map')}</h2><p className="tnum">{plural(map.counts.outside_total, '1 source · {n} work from its reference list matched in OpenAlex', '1 source · {n} works from its reference list matched in OpenAlex')}</p></div>
      <div className="cm-note">{t('Links between sources need at least two sources in the research. For now the map shows the one source’s reference list; you can add candidates from here.')}</div></>
    : <div className="cm-sum"><h2>{t('Source citation map')}</h2><p className="tnum">{[plural(map.nodes.length, '{n} source', '{n} sources'), plural(linkCount, '{n} citation link', '{n} citation links'),
      map.counts.outside_total > 0 && plural(map.counts.outside_total, '{n} work outside this research is cited by at least {k} sources', '{n} works outside this research are cited by at least {k} sources', { k: map.counts.outside_threshold })].filter(Boolean).join(' · ')}</p></div>
  const foot = <div className="cm-foot">
    <p>{t('Links come from OpenAlex’s reference records; no model is called. When a source cites another, the arrow goes from the citing work to the cited one.')}</p>
    <p>{t('Works whose reference list is missing in OpenAlex miss their links too. A link only shows a citation; it does not show that two works say the same thing.')}</p>
  </div>

  if (!map.nodes.length) return <div className="mk citemap">{summary}<p className="cm-empty">{t('No sources yet.')}</p>{foot}</div>
  if (noOpenAlex) return <div className="mk citemap"><div className="cm-sum"><h2>{t('Source citation map')}</h2></div>
    <p className="cm-empty">{t('None of this research’s sources has an OpenAlex record, so no citation link can be drawn.')}{noDoi && <> {noDoi}.</>}</p>{foot}</div>

  // ---- the map ----------------------------------------------------------------------------------------------------
  const svg = drawn && (() => {
    const { layout: lay, links } = drawn
    const edges = links.map(([s, d], i) => {
      let cls = 'e'
      if (s === focus) cls += ' out'; else if (d === focus) cls += ' in'; else if (focus) cls += ' dim'
      if (needle && !(hits.has(s) || hits.has(d))) cls += ' dim'
      const on = cls.includes(' out') || cls.includes(' in')
      return <path key={`${s}>${d}`} className={cls} d={paths[i]} markerEnd={`url(#${markerId}${on ? 'on' : ''})`} />
    })
    const nodes = visible.map(n => {
      // Neighbouring year columns put their labels on opposite sides, so names in one row do not run into each other.
      const p = lay.pos.get(n.key)!, rr = radius(indeg(n.key))
      let cls = `n ${n.kind}`
      if (n.key === selected) cls += ' sel'
      if (focus && !neighbours.has(n.key)) cls += ' dim'
      if (needle) cls += hits.has(n.key) ? ' hit' : ' dim'
      const label = !lay.dense || zoom.k >= 2 || n.key === selected || n.key === hover || hits.has(n.key) || (focus !== null && neighbours.has(n.key))
      const unread = n.kind !== 'outside' && !n.read
      return <g key={n.key} className={cls} data-key={n.key} tabIndex={0} role="button" transform={`translate(${p.x.toFixed(1)},${p.y.toFixed(1)}) scale(${(1 / zoom.k).toFixed(3)})`}
        aria-label={`${nameOf(n)}, ${t(KIND_LABELS[n.kind])}, ${plural(indeg(n.key), 'cited by {n} source in this research', 'cited by {n} sources in this research')}`}
        aria-pressed={n.key === selected}
        onClick={() => select(n.key)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(n.key) } }}
        onMouseEnter={() => hoverTo(n.key)} onMouseLeave={() => hoverTo(null)}>
        <circle className="ring" r={rr + 5} />{unread && <circle className="noref" r={rr + 4} />}<circle className="c" r={rr} />
        {label && <text y={layout === 'time' && (p.col ?? 0) % 2 ? -(rr + 8) : rr + 15} textAnchor="middle">{n.short}{layout === 'net' && n.year ? ` ${n.year}` : ''}</text>}
        <title>{titleOf(n, describable)}</title>
      </g>
    })
    return <svg ref={svgRef} viewBox={`0 0 ${lay.W} ${lay.H}`} role="group" aria-label={t('Source citation map')} className={panning ? 'panning' : undefined}
      style={{ minWidth: lay.W > 920 ? Math.round(lay.W * 0.8) : 640 }}
      onPointerDown={e => {
        // Dragging the background moves the drawing; a press on a work still selects it.
        if (e.button !== 0 || (e.target as Element).closest('.n')) return
        pan.current = { px: e.clientX, py: e.clientY, x: zoom.x, y: zoom.y }
        e.currentTarget.setPointerCapture(e.pointerId)
        setPanning(true)
      }}
      onPointerMove={e => {
        const start = pan.current
        if (!start) return
        const scale = lay.W / e.currentTarget.getBoundingClientRect().width
        setZoom(z => ({ ...z, x: start.x + (e.clientX - start.px) * scale, y: start.y + (e.clientY - start.py) * scale }))
      }}
      onPointerUp={() => { pan.current = null; setPanning(false) }} onPointerCancel={() => { pan.current = null; setPanning(false) }}>
      <defs>
        <marker id={markerId} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path className="arrow" d="M0,0 L8,4 L0,8 z" /></marker>
        <marker id={`${markerId}on`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path className="arrow a-on" d="M0,0 L8,4 L0,8 z" /></marker>
      </defs>
      <g transform={`translate(${zoom.x.toFixed(1)} ${zoom.y.toFixed(1)}) scale(${zoom.k.toFixed(3)})`}>
      {layout === 'time' && <g className="axis">{lay.axis.map(a => <g key={a.label}><line x1={a.x} x2={a.x} y1={22} y2={lay.H - 48} /><text x={a.x} y={lay.H - 28} textAnchor="middle">{a.label}</text></g>)}</g>}
      <g>{edges}</g><g>{nodes}</g>
      </g>
    </svg>
  })()
  const anyUnread = visible.some(n => n.kind !== 'outside' && !n.read)
  const legend = <div className="cm-legend"><span><i />{t('Cited by the selected source')}</span><span><i className="dash" />{t('Citing the selected source')}</span>
    <span>{t('Circle size: how many sources in this research cite it')}</span>{layout === 'time' && <span>{t('Left to right: publication year')}</span>}
    {anyUnread && <span><b className="cm-noref-key" aria-hidden />{t('Dotted ring: reference list not read')}</span>}</div>

  const centre = drawn ? { x: drawn.layout.W / 2, y: drawn.layout.H / 2 } : { x: 0, y: 0 }
  const zoomBar = drawn && <div className="cm-zoom">
    <button type="button" className="ib" aria-label={t('Zoom in')} title={t('Zoom in')} disabled={zoom.k >= ZOOM_MAX} onClick={() => setZoom(z => zoomAt(z, centre, 1.5))}><ZoomIn size={16} aria-hidden /></button>
    <button type="button" className="ib" aria-label={t('Zoom out')} title={t('Zoom out')} disabled={zoom.k <= ZOOM_MIN} onClick={() => setZoom(z => zoomAt(z, centre, 1 / 1.5))}><ZoomOut size={16} aria-hidden /></button>
    <button type="button" className="ib" aria-label={t('Show the whole map')} title={t('Show the whole map')} disabled={zoom === WHOLE_MAP} onClick={() => setZoom(WHOLE_MAP)}><Maximize size={16} aria-hidden /></button>
    <span className="tnum">{Math.round(zoom.k * 100)}%</span>
    <span className="cm-zoom-hint">{t('⌘ or Ctrl + scroll, or pinch, to zoom; drag to move')}</span>
  </div>

  const node = selected ? graph.byKey.get(selected) ?? null : null
  const row = (n: MapNode) => {
    const c = indeg(n.key), w = Math.max(4, Math.round(60 * c / maxIn))
    const isAdded = n.openalexId !== null && added.has(n.openalexId)
    return <div className="cm-row" key={n.key}>
      <span className="k">{n.kind === 'outside' && !n.title && n.openalexId ? n.openalexId : nameOf(n)}</span>
      <div className="t"><button type="button" onClick={() => select(n.key)}>{titleOf(n, describable)}</button>
        <small className="tnum"><span className="bar" style={{ width: w }} />{plural(c, 'cited by {n} source', 'cited by {n} sources')}
          {n.kind === 'outside' ? n.removed && <> · {t('Removed from this research earlier')}</> : <> · <span className={`dot d-${n.kind}`} />{t(KIND_LABELS[n.kind])}</>}</small></div>
      {n.kind === 'outside' && n.title !== null && (isAdded
        ? <span className="done"><Check size={15} aria-hidden />{t('In candidates')}</span>
        : <button type="button" className="ghost" disabled={adding !== null} onClick={() => void add(n)}>{t('Add to candidates')}</button>)}
    </div>
  }

  return <div className="mk citemap">
    {summary}
    {planRow}
    {banner}
    <div className="cm-ctrl">
      {KINDS.map(k => <button key={k} type="button" className="chipf" aria-pressed={show[k]} onClick={() => setShow(s => ({ ...s, [k]: !s[k] }))}>
        <span className={`dot d-${k}`} />{t(KIND_LABELS[k])} <span className="tnum">{counts[k]}</span></button>)}
      {show.pending && pendingRanked.length > PENDING_SHOWN && <span className="cm-more tnum">
        {allPending ? t('All {n} undecided shown', { n: pendingRanked.length }) : t('{shown} of {n} undecided shown, the most cited', { shown: PENDING_SHOWN, n: pendingRanked.length })}
        <button type="button" className="link" onClick={() => setAllPending(v => !v)}>{allPending ? t('Show the {n} most cited', { n: PENDING_SHOWN }) : t('Show all')}</button></span>}
      <span className="sp" />
      <div className="seg" role="group" aria-label={t('Layout')}>
        <button type="button" aria-pressed={layout === 'time'} onClick={() => setLayout('time')}>{t('Timeline')}</button>
        <button type="button" aria-pressed={layout === 'net'} onClick={() => setLayout('net')}>{t('Network')}</button>
      </div>
      <label className="search"><Search size={16} aria-hidden /><input type="search" placeholder={t('Search sources')} aria-label={t('Search the map for a source')} value={query} onChange={e => setQuery(e.target.value)} /></label>
    </div>
    <div className="cm-stage">
      <div className="cm-mapbox">{zoomBar}{svg ?? <p className="cm-none">{t('No source matches the filters.')}</p>}{legend}</div>
      <div className="cm-detail">{node ? <Detail node={node} graph={graph} budgetStop={budgetStop} added={node.openalexId !== null && added.has(node.openalexId)}
        adding={adding !== null} describable={describable} onSelect={select} onOpen={onOpenSource} onAdd={add} /> : <p className="meta">{t('Choose a source on the map.')}</p>}</div>
    </div>
    <div className="cm-cols">
      {!single && <section><h3>{t('The core of this research')}</h3><p className="sub">{t('The sources this research’s sources cite most.')}</p>{core.length ? core.map(row) : <p className="sub">{t('None.')}</p>}</section>}
      <section><h3>{t('Often-cited works outside this research')}</h3><p className="sub">{t('They appear often in the reference lists of its sources but are not in this research. They may be worth a look.')}</p>
        {outsideRanked.length ? outsideRanked.map(row) : <p className="sub">{t('None.')}</p>}</section>
    </div>
    {foot}
  </div>
}

function Detail({ node, graph, budgetStop, added, adding, describable, onSelect, onOpen, onAdd }: {
  node: MapNode; graph: Graph; budgetStop: boolean; added: boolean; adding: boolean; describable: boolean
  onSelect: (key: string) => void; onOpen: (sourceVersionId: string) => void; onAdd: (node: MapNode) => void
}) {
  const byYear = (a: MapNode, b: MapNode) => (b.year ?? 0) - (a.year ?? 0)
  const cites = graph.links.filter(([a]) => a === node.key).map(([, b]) => graph.byKey.get(b)).filter((n): n is MapNode => Boolean(n)).sort(byYear)
  const citedBy = graph.links.filter(([, b]) => b === node.key).map(([a]) => graph.byKey.get(a)).filter((n): n is MapNode => Boolean(n)).sort(byYear)
  const outside = node.kind === 'outside'
  const unread = !outside && !node.read
  const list = (items: MapNode[]) => items.length
    ? items.map(m => <button type="button" key={m.key} onClick={() => onSelect(m.key)}><span className={`dot d-${m.kind}`} /><span>{nameOf(m)} · {titleOf(m, describable)}</span></button>)
    : <p>{t('None.')}</p>
  const facts = [node.venue, node.year, node.citedBy !== null ? t('{n} citations (OpenAlex)', { n: node.citedBy.toLocaleString(uiLocale()) }) : null].filter(v => v !== null && v !== '')
  return <>
    <span className="cm-pill"><span className={`dot d-${node.kind}`} />{t(KIND_LABELS[node.kind])}</span>
    <h3>{titleOf(node, describable)}</h3>
    <p className="meta">{node.authors.length > 0 && <>{node.authors.join(', ')}<br /></>}{facts.length > 0 ? <span className="tnum">{facts.join(' · ')}</span> : node.openalexId}</p>
    {node.removed && <p className="meta">{t('Removed from this research earlier')}</p>}
    <div className="cm-stats tnum">
      <div><b>{graph.indeg.get(node.key) ?? 0}</b><small>{t('sources cite this')}</small></div>
      <div><b>{outside ? '–' : unread ? '?' : graph.outdeg.get(node.key) ?? 0}</b><small>{t('sources it cites')}</small></div>
    </div>
    {unread && <p className="meta cm-warn">{t(budgetStop ? 'Reference list not read (OpenAlex quota). The sources it cites are missing.' : 'Reference list not read. The sources it cites are missing.')}</p>}
    <div className="acts">
      {outside && node.title === null
        ? <p className="meta">{t(describable ? 'Press Read reference lists above to fetch its title and authors; it can be added after that.'
          : 'Without a record it cannot be added to the research.')}</p>
        : outside
        ? added ? <span className="cm-pill"><span className="dot d-included" />{t('In the candidate list')}</span>
          : <button type="button" className="btn-pri" disabled={adding} onClick={() => onAdd(node)}><Plus size={16} aria-hidden />{t('Add to candidates')}</button>
        : node.sourceVersionId && <button type="button" className="btn-pri" onClick={() => onOpen(node.sourceVersionId!)}><FileText size={16} aria-hidden />{t('Open source')}</button>}
      {node.doi && <a className="ghost" href={`https://doi.org/${node.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//, '')}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" />DOI</a>}
    </div>
    <div className="cm-lst"><h4>{t('Works it cites')} · {cites.length}</h4>{outside ? <p>{t('Reference lists of works outside this research are not read.')}</p> : list(cites)}</div>
    <div className="cm-lst"><h4>{t('Works citing it')} · {citedBy.length}</h4>{list(citedBy)}</div>
  </>
}
