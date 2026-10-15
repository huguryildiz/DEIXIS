import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { AlignLeft, Check, ChevronLeft, ChevronRight, Copy, Ellipsis, FileText, FileUp, Info, Link as LinkIcon, ListMinus, LoaderCircle, Maximize2, Minimize2, Replace, RotateCcw, ScanText, Search, Sigma, Trash2, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, assetUrl, shellApi, type Asset, type AssetText, type Claim, type Passage, type PdfDiscovery, type Source } from './api'
import { citedText, locatorText, providerName, retractionNote, serviceErrors, serviceKind, versionText } from './labels'
import { t, uiLocale } from './i18n'
import { PassageMathText } from './PassageMathText'
import { PdfViewer } from './PdfViewer'
import { OCR_LABEL, ocrOffer } from './ocr'
import { SourceKey } from './SourceKey'
import { PdfTextDocument, type CitationLabels } from './PdfTextDocument'
import { AUTHOR_NOTE, readablePassageText } from './pdfText'
import { Notice } from './Notice'
import { OccurrenceNotice, StoredPdfNotice } from './occurrence'
import { StackPanel } from './research/SplitPanel'
import { usePanels } from './research/usePanelStack'
import { citationStyles, formatBibtex, formatReferenceText, useCitationStyle } from './citations'
import { useToast } from './Toast'
import type { OcrContext } from './research/shared'

// Marks every located anchor; overlapping anchors are merged into one mark, and the first mark is scrolled into view
// (`scroll`: off where several quotes share one view, as in the Citation panel).
export function HighlightedPassageText({ passage, highlightTexts, markLabel, scroll = true }: { passage: Pick<Passage, 'text' | 'kind'>; highlightTexts: string[]; markLabel?: string; scroll?: boolean }) {
  const highlightRef = useRef<HTMLElement>(null)
  const ranges: [number, number][] = []
  for (const [start, end] of highlightTexts.map(text => [passage.text.indexOf(text), passage.text.indexOf(text) + text.length]).filter(([start]) => start >= 0).sort((a, b) => a[0] - b[0])) {
    const last = ranges[ranges.length - 1]
    if (last && start <= last[1]) last[1] = Math.max(last[1], end)
    else ranges.push([start, end])
  }
  const first = ranges[0]?.[0] ?? -1

  useEffect(() => {
    if (first < 0 || !scroll) return
    const frame = requestAnimationFrame(() => highlightRef.current?.scrollIntoView({ block: 'center' }))
    return () => cancelAnimationFrame(frame)
  }, [passage, first, scroll])

  if (!ranges.length) return <PassageMathText text={readablePassageText(passage.kind, passage.text)} />

  return <>
    {ranges.map(([start, end], i) => <Fragment key={start}>
      <PassageMathText text={readablePassageText(passage.kind, passage.text.slice(i ? ranges[i - 1][1] : 0, start))} />
      <mark ref={i === 0 ? highlightRef : undefined} className="citation-highlight" aria-label={markLabel ?? t('Exact text cited in the answer')}>
        <PassageMathText text={readablePassageText(passage.kind, passage.text.slice(start, end))} />
      </mark>
    </Fragment>)}
    <PassageMathText text={readablePassageText(passage.kind, passage.text.slice(ranges[ranges.length - 1][1]))} />
  </>
}

// What the research page lets Source details do with a source of this research (P14, §2.2): find or attach a PDF,
// replace it, take the source out of the research, and the text tools that the Sources rows also offer. Other places
// (Library, Trash, the evidence table, the queue) open the panel without them and show only what needs no action.
export type SourceActions = {
  busy: boolean
  // The works whose open-copy lookup is running, one entry per lookup.
  finding: string[]
  onFind: (source: Source) => Promise<boolean>
  onAttach: (source: Source) => void
  onReplace: (source: Source, assetId: string) => void
  onRemove: (source: Source) => void
  onReextract: (source: Source, assetId: string) => void
  onRereadEquations: (source: Source, assetId: string) => void
  ocr: OcrContext
}

type Tab = 'abs' | 'text' | 'pdf'
// The services the open-copy lookup asks first, in its order (documents/acquisition.py); Europe PMC and Web Search are
// asked only when these give no file, so they are named only once their answers are recorded.
// A lookup DEIXIS recorded without sending a request (P15): the service needed a key or contact setting that is not
// set, or the OpenAlex daily budget was closed. It is named apart from the services that were asked.
const NOT_SENT = new Set(['missing_contact_email', 'missing_core_key', 'missing_serpapi_key'])
const notSent = (d: PdfDiscovery) => NOT_SENT.has(d.error_code ?? '') || (d.error_code === 'quota_exhausted' && d.http_status === null)
// Whether a stored PDF has text a new answer can read, from its extraction state (a kept file can have none).
const textState = (asset: Asset | null | undefined): 'text' | 'none' | 'pending' | null =>
  !asset ? null : ['succeeded', 'partial'].includes(asset.extraction_status) ? 'text' : ['no_text', 'failed'].includes(asset.extraction_status) ? 'none' : 'pending'

// The proxy builds the link the browser opens, as the backend's `proxy.link` does: a `{url}` template, or a prefix.
function proxied(proxy: string, target: string) {
  if (proxy.includes('{url}')) return proxy.replace('{url}', encodeURIComponent(target))
  return proxy + (/[&#]/.test(target) ? encodeURIComponent(target) : target)
}

async function writeClipboard(text: string) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  throw new Error('clipboard unavailable')
}

// Marks of one located anchor can be cut into pieces (math, links) and an anchor can run over a paragraph break; the
// marks of consecutive blocks are one place in the text.
function markGroups(root: HTMLElement | null) {
  if (!root) return []
  const groups: HTMLElement[][] = []
  let lastBlock: Element | null = null
  for (const mark of Array.from(root.querySelectorAll<HTMLElement>('mark.citation-highlight'))) {
    const block = mark.closest('[id]')
    const group = groups[groups.length - 1]
    if (group && (block === lastBlock || (lastBlock && lastBlock.nextElementSibling === block))) group.push(mark)
    else groups.push([mark])
    lastBlock = block
  }
  return groups
}

// pdfRemoved: the passage's PDF was removed from the source; its stored text still opens, the PDF view stays off.
// A passage also reports this itself (evidence_status, D45), as it does a replaced file or an earlier text extraction.
// sources: the research's source rows; the one matching the opened source adds its screening state, similarity and citation.
// onRestoreSource: offered when the passage's source was removed from this research (D50).
// sourceVersionId: open a source rather than a passage (one of `sources`): its PDF text, else its abstract, else its details alone.
// initialPage: the PDF page a file opened without a passage starts on. citationLabels: the strip's words when the
// text is opened for something other than an answer's citation (the human queue, slice 17).
// latestAnswer: the research's latest valid answer, whose claims the details line counts ("cited in N claims of Vn").
// actions: what the research page lets the panel do (P14); findOnOpen starts the open-copy lookup once on open (the
// Citation panel's Find PDF).
export function PassageSheet({ researchId, passageId, assetId = null, sourceVersionId = null, initialView = 'text', initialPage = 1, highlightText, highlightTexts, expectHighlight = false, citationLabels, pdfRemoved = false, sources, dark, onClose, onRestoreSource, asPanel = false, latestAnswer = null, actions, findOnOpen = false }: { researchId: string; passageId: string | null; assetId?: string | null; sourceVersionId?: string | null; initialView?: 'text' | 'pdf'; initialPage?: number; highlightText?: string | null; highlightTexts?: string[]; expectHighlight?: boolean; citationLabels?: CitationLabels; pdfRemoved?: boolean; sources?: Source[]; dark: boolean; onClose: () => void; onRestoreSource?: (sourceVersionId: string) => void; asPanel?: boolean; latestAnswer?: { version: number; claims: Claim[] } | null; actions?: SourceActions; findOnOpen?: boolean }) {
  const [passage, setPassage] = useState<Passage | null>(null)
  const [assetText, setAssetText] = useState<AssetText | null>(null)
  // The whole extracted text of the PDF a cited passage comes from: undefined while it loads, null when the passage opens alone.
  const [passageDocument, setPassageDocument] = useState<AssetText | null | undefined>(null)
  const [currentDocument, setCurrentDocument] = useState<AssetText | null>(null)
  // The source's own abstract, and the text of its PDF, read for the Abstract and Plain text tabs when the opened
  // passage is not that text (an abstract citation of a source that has a PDF, a PDF page of a source with an abstract).
  // null: not read yet; false: the read failed (it is not asked again until the panel opens something else).
  const [abstractPassage, setAbstractPassage] = useState<Passage | null | false>(null)
  // The source PDF's text is kept with the file it was read from: when the source's file changes (Replace PDF) the
  // earlier text no longer counts and the new file's is read.
  const [extraText, setExtraText] = useState<{ assetId: string; value: AssetText | false } | null>(null)
  const [comparing, setComparing] = useState(false)
  const [loadingCurrent, setLoadingCurrent] = useState(false)
  const [comparisonError, setComparisonError] = useState('')
  const comparisonRequest = useRef(0)
  const [error, setError] = useState('')
  // The PDF view reads at full workspace width; the text view starts as a side sheet.
  const [full, setFull] = useState(initialView === 'pdf')
  const [allAuthors, setAllAuthors] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [tab, setTab] = useState<Tab>(initialView)
  // The open-copy lookup started here (P15): the lookups recorded before it, so its own answers are the ones after them.
  // `id` and `svid` bind a lookup's completion to the lookup and work it was started for: an earlier lookup that ends
  // later never marks a newer one done.
  const [find, setFind] = useState<{ id: number; svid: string; before: number; hadPdf: boolean; done: boolean } | null>(null)
  const lookupSeq = useRef(0)
  // The target a lookup asked for on open was started for; cleared when the panel opens something else or closes.
  const askedFind = useRef<string | null>(null)
  const [proxy, setProxy] = useState<{ address: string; label: string } | null>(null)
  const [style] = useCitationStyle()
  const toast = useToast()
  const textView = useRef<HTMLDivElement>(null)
  const [groups, setGroups] = useState(0)
  const [groupAt, setGroupAt] = useState(0)
  const opened = sourceVersionId ? sources?.find(s => s.source_version_id === sourceVersionId) : undefined
  const openAssetId = assetId ?? ((!passageId && opened?.access.assets[0]?.id) || null)
  const openPassageId = passageId ?? ((!openAssetId && opened?.access.abstract_passage_id) || null)
  const detailsOnly = Boolean(opened && !openPassageId && !openAssetId)

  useEffect(() => {
    setPassage(null)
    setAssetText(null)
    setPassageDocument(null)
    setAbstractPassage(null); setExtraText(null); setFind(null)
    askedFind.current = null
    setCurrentDocument(null); setComparing(false); setLoadingCurrent(false); setComparisonError('')
    comparisonRequest.current += 1
    setError('')
    setAllAuthors(false)
    setTab(openPassageId || openAssetId ? initialView : 'abs')
    setFull(initialView === 'pdf')
    if (!openPassageId && !openAssetId) return
    let cancelled = false
    const request = openPassageId
      ? api.passage(researchId, openPassageId).then(p => {
        if (cancelled) return
        // Pin even a current citation to its occurrence: a promotion can happen between these two requests.
        const extractionId = p.occurrence?.extraction_id
        const inDocument = p.kind !== 'abstract' && p.asset_id && extractionId && (p.evidence_status === 'current' || p.evidence_status === 'text_superseded')
        setPassageDocument(inDocument ? undefined : null)
        setPassage(p)
        // An abstract opens on its own tab (mockup `detail()`: Abstract first when there is no PDF text).
        if (p.kind === 'abstract' && initialView !== 'pdf') setTab('abs')
        if (inDocument) api.assetText(researchId, p.asset_id!, extractionId)
          .then(value => { if (!cancelled) setPassageDocument(value.occurrence?.extraction_id === extractionId && value.passages.some(item => item.physical_page === p.physical_page) ? value : null) })
          .catch(() => { if (!cancelled) setPassageDocument(null) })
      })
      : api.assetText(researchId, openAssetId!).then(value => { if (!cancelled) setAssetText(value) })
    request.catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true; comparisonRequest.current += 1 }
  }, [researchId, openPassageId, openAssetId, initialView])

  const source = passage?.source ?? assetText?.source ?? (detailsOnly && opened ? { ...opened, id: opened.source_version_id } : undefined)
  const abstract = passage?.kind === 'abstract'
  const highlights = highlightTexts ?? (highlightText ? [highlightText] : [])
  const highlightAvailable = Boolean(passage && highlights.length && highlights.every(text => passage.text.includes(text)))
  const highlightKey = highlights.join('\u0000')
  const citation = useMemo(() => passage ? { page: passage.physical_page, texts: highlightKey ? highlightKey.split('\u0000') : [], expected: expectHighlight, labels: citationLabels } : null, [passage, highlightKey, expectHighlight, citationLabels])
  const status = passage?.evidence_status ?? 'current'
  const earlier = Boolean(passage?.occurrence && !passage.occurrence.is_current && status === 'text_superseded')
  const shownDocument = comparing ? currentDocument : passageDocument
  const toggleCurrent = async () => {
    if (comparing) { setComparing(false); return }
    if (!passage?.asset_id) return
    const requestId = ++comparisonRequest.current
    setLoadingCurrent(true); setComparisonError('')
    try {
      const value = await api.assetText(researchId, passage.asset_id)
      if (requestId === comparisonRequest.current) { setCurrentDocument(value); setComparing(true) }
    } catch (e) { if (requestId === comparisonRequest.current) setComparisonError(e instanceof Error ? e.message : String(e)) }
    finally { if (requestId === comparisonRequest.current) setLoadingCurrent(false) }
  }
  const row = source ? sources?.find(s => s.source_version_id === source.id) : undefined
  const removed = pdfRemoved || status === 'pdf_removed'
  // The PDF of the opened passage or file; an abstract (or a source opened for its details) shows the source's own PDF.
  const rowAssetId = row?.access.assets[0]?.id ?? null
  const pdfAssetId = removed ? null : passage?.asset_id ?? assetText?.asset.id ?? ((abstract || detailsOnly) ? rowAssetId : null)
  // Europe PMC's open-access text drawn as a PDF by DEIXIS (SW21): every page it names says "rendered". Each view
  // takes it from what it shows: the text view from the passage read from the PDF or the document shown, the PDF view
  // from the opened file's stored record (an abstract passage carries none of its own).
  // The text read for the source's current file, if it has been read: null not yet, false the read failed.
  const extra = extraText && extraText.assetId === rowAssetId ? extraText.value : null
  const textRendition = passage && !abstract ? Boolean(passage.rendition) : Boolean((assetText ?? (extra || null))?.asset.rendition)
  const pdfRendition = passage && !abstract && passage.asset_id === pdfAssetId ? Boolean(passage.rendition)
    : assetText && assetText.asset.id === pdfAssetId ? Boolean(assetText.asset.rendition)
    : Boolean(row?.access.assets.find(a => a.id === pdfAssetId)?.rendition)
  const rendition = tab === 'pdf' ? pdfRendition : tab === 'text' ? textRendition : false
  // The arXiv source version a 'latex_source' passage's equations came from (D104); omitted gracefully if not found.
  const sourceAsset = passage?.asset_id ? row?.access.assets.find(a => a.id === passage.asset_id) : undefined
  const arxivVersion = sourceAsset?.equations?.route === 'arxiv_source' ? sourceAsset.equations.source?.version ?? null : null
  const abstractId = abstract ? passage!.id : row?.access.abstract_passage_id ?? opened?.access.abstract_passage_id ?? null
  const abstractShown = abstract ? passage : abstractPassage || null
  // The text the Plain text tab reads when the opened passage is not a PDF page: the opened file's, else the source's PDF.
  const otherText = assetText ?? (extra || null)
  const needsOtherText = tab === 'text' && !assetText && extra === null && Boolean(rowAssetId) && !removed && (abstract || detailsOnly)
  const needsAbstract = tab === 'abs' && abstractPassage === null && Boolean(abstractId) && !abstract

  useEffect(() => {
    if (!needsAbstract || !abstractId) return
    let live = true
    api.passage(researchId, abstractId).then(p => { if (live) setAbstractPassage(p) }, () => { if (live) setAbstractPassage(false) })
    return () => { live = false }
  }, [needsAbstract, abstractId, researchId])
  useEffect(() => {
    if (!needsOtherText || !rowAssetId) return
    // A read still running for an earlier file is let go when the file changes, and its answer is kept with its own
    // file id, so it can never stand for the new file's text.
    let live = true
    const assetId = rowAssetId
    api.assetText(researchId, assetId).then(value => { if (live) setExtraText({ assetId, value: value.asset.id === assetId ? value : false }) }, () => { if (live) setExtraText({ assetId, value: false }) })
    return () => { live = false }
  }, [needsOtherText, rowAssetId, researchId])

  // The proxy's address and name, for "Open via …" on a work without a PDF (P14).
  const wantsProxy = Boolean(asPanel && actions)
  useEffect(() => {
    if (!wantsProxy) return
    let live = true
    shellApi.proxySettings().then(value => { if (live && value.address) setProxy({ address: value.address, label: value.label ?? value.label_default ?? t('institution proxy') }) }, () => undefined)
    return () => { live = false }
  }, [wantsProxy])

  // The places marked in the text view, for "Cited passage i of N" (P17). Counted after the view has drawn its marks.
  const documentShown = tab === 'text' && Boolean((passage && !abstract && shownDocument) || otherText)
  useEffect(() => {
    if (!documentShown) return
    const frame = requestAnimationFrame(() => { setGroups(markGroups(textView.current).length); setGroupAt(0) })
    return () => cancelAnimationFrame(frame)
  }, [documentShown, shownDocument, otherText, comparing, showNotes, highlightKey])
  const goToGroup = (index: number) => {
    const list = markGroups(textView.current)
    if (!list.length) return
    const next = (index + list.length) % list.length
    setGroupAt(next)
    list[next][0].scrollIntoView({ block: 'center' })
  }

  const hasPdf = Boolean(pdfAssetId)
  // The file and its text are told apart (P12): a passage read from the PDF, or its loaded text, says there is text;
  // otherwise the stored extraction state of the file does. A kept file can have no text (no text layer, a failed read).
  const fileAsset = pdfAssetId ? row?.access.assets.find(item => item.id === pdfAssetId) ?? null : null
  const loadedText = (passage && !abstract) ? true : assetText ? assetText.passages.length > 0 : extra ? extra.passages.length > 0 : null
  const pdfText: 'text' | 'none' | 'pending' | null = loadedText === true ? 'text' : loadedText === false ? 'none' : textState(fileAsset) ?? (hasPdf ? 'pending' : null)
  const finding = Boolean(row && actions?.finding.includes(row.source_version_id))
  const canFind = Boolean(row && actions && row.doi && !row.access.assets.length && row.version_role !== 'other_version')
  const startFind = async () => {
    if (!row || !actions || finding) return
    const id = ++lookupSeq.current, svid = row.source_version_id
    setFind({ id, svid, before: row.access.pdf_discoveries.length, hadPdf: row.access.assets.length > 0, done: false })
    const ok = await actions.onFind(row)
    setFind(current => (current && current.id === id && current.svid === svid ? (ok ? { ...current, done: true } : null) : current))
  }
  // Find PDF from the Citation panel: one lookup per opening, for the work of the passage this opening loaded.
  const findKey = findOnOpen ? `${openPassageId ?? ''}|${openAssetId ?? ''}` : null
  useEffect(() => {
    if (!findKey || askedFind.current === findKey || !canFind || (openPassageId && passage?.id !== openPassageId)) return
    askedFind.current = findKey
    void startFind()
  })  // eslint-disable-line react-hooks/exhaustive-deps

  const pdfUnavailable = removed ? 'The PDF was removed from this source; its passages still open as text.' : 'Nothing is downloaded from paywalled sites. Look for an open copy or attach your own file.'
  const selectionText = { included: 'Included', excluded: 'Excluded', pending: 'Undecided' } as const
  const originText: Record<Source['selection']['origin'], string | null> = { user: 'your decision', model_proposal: 'model proposal', code_rule: 'code rule', default: null }
  const isOpen = openPassageId !== null || openAssetId !== null || detailsOnly
  const description = passage ? t('Cited passage: {locator}', { locator: locatorText(passage) }) : assetText ? t('PDF source') : detailsOnly ? t('Source') : t(error ? 'Unavailable' : 'Loading passage…')
  const choose = (next: Tab) => { setTab(next); if (next === 'pdf' && hasPdf) setFull(true) }
  const pages = (doc: AssetText) => new Set(doc.passages.map(item => item.physical_page)).size
  const citedClaims = row && latestAnswer ? latestAnswer.claims.filter(c => c.evidence.some(e => e.source_version_id === row.source_version_id)).length : null
  const doiHref = source?.doi ? `https://doi.org/${source.doi}` : source?.landing_url ?? null
  const asSource = (): Source | null => row ?? (source ? { ...(source as unknown as Source), source_version_id: source.id, publication_type: null, volume: null, issue: null, pages: null } : null)
  const copyText = async (text: string, done: string) => {
    try { await writeClipboard(text); toast('success', done) } catch { toast('error', t('Could not copy to the clipboard.')) }
  }
  const copyCitation = () => { const s = asSource(); if (s) void copyText(formatReferenceText(style, s), t('Citation copied ({style}).', { style: t(citationStyles[style].label) })) }
  const copyBibtex = () => { const s = asSource(); if (s) void copyText(formatBibtex(s), t('Citation copied (BibTeX).')) }
  const asset = row?.access.assets[0]
  const ocr = asset && actions ? ocrOffer(asset, actions.ocr.tool, actions.ocr.runs) : null
  const busy = Boolean(actions?.busy)

  // Find PDF and Attach PDF, the actions of an empty tab (P18).
  const emptyActions = row && actions && <div className="acts">
    {canFind && <button type="button" className="btn-pri" disabled={busy || finding} onClick={() => { void startFind() }}><Search size={14} aria-hidden />{t('Find PDF')}</button>}
    {row.version_role !== 'other_version' && <Button variant="outline" size="sm" className="ghost" disabled={busy} onClick={() => actions.onAttach(row)}><FileUp size={14} aria-hidden />{t('Attach PDF')}</Button>}
  </div>

  // The open-copy lookup started from this panel (P15). While it runs no service is named: it is one request and its
  // steps are not reported. After it, the services it asked, each with its recorded answer, apart from the ones it
  // recorded without asking (a key or contact setting missing, the daily budget closed), and whether a file came; what
  // the file holds (text a new answer can read, or none) comes from its stored extraction, not from its presence.
  const findBlock = (() => {
    if (!row || ((!find || find.svid !== row.source_version_id) && !finding)) return null
    if (finding || !find?.done) return <div className="notice answer-notice is-info find-block" role="status">
      <LoaderCircle size={16} className="pdf-search-spin" aria-hidden />
      <div className="notice-body"><p><b>{t('Looking for an open copy…')}</b></p></div>
    </div>
    const records = row.access.pdf_discoveries.slice(find.before)
    const sent = records.filter(d => !notSent(d))
    const providers = [...new Set(sent.map(d => d.provider))]
    const skipped = records.filter(d => notSent(d) && !providers.includes(d.provider))
    const answered = (provider: string) => sent.filter(d => d.provider === provider).some(d => ['completed', 'zero_results'].includes(d.status))
    const pills = providers.length > 0 && <div className="pills">{providers.map(id => <span key={id} className={`pill ${answered(id) ? 'ok' : 'warn'}`}>{answered(id) ? <Check size={12} aria-hidden /> : <TriangleAlert size={12} aria-hidden />}{providerName(id)}</span>)}</div>
    const notAsked = skipped.length > 0 && <p className="find-skipped">{t('Not asked:')} {[...new Map(skipped.map(d => [d.provider, d])).values()].map(d => t(serviceErrors[serviceKind(d.error_code, d.http_status)], { service: providerName(d.provider) })).join(' ')}</p>
    const names = providers.map(providerName)
    const list = names.length > 1 ? t('{a} and {b}', { a: names.slice(0, -1).join(', '), b: names[names.length - 1] }) : names[0] ?? ''
    const got = row.access.assets[0]
    if (!find.hadPdf && got) {
      const via = row.access.pdf_candidates.find(c => c.access_status === 'downloaded')
      const facts = [via && providerName(via.provider), versionText(row.version_label), got.page_count ? t(got.page_count === 1 ? '{n} page' : '{n} pages', { n: got.page_count }) : null].filter(Boolean).join(', ')
      const read = textState(got)
      const status = got.extraction_status === 'partial' ? t('Text was extracted from some of its pages (no OCR); a new answer can read them. Citations name the copy that was read.')
        : read === 'text' ? t('Its text was extracted page by page (no OCR); a new answer can read it. Citations name the copy that was read.')
        : got.extraction_status === 'no_text' ? t('The file is kept, but it has no text layer to extract, so a new answer cannot read it yet.')
        : read === 'none' ? t('The file is kept, but its text could not be extracted, so a new answer cannot read it yet.')
        : t('The file is kept; its text has not been read yet.')
      return <div className={`notice answer-notice ${read === 'text' ? 'is-info' : 'is-attention'} find-block`} role="status">{read === 'text' ? <Check size={16} aria-hidden /> : <TriangleAlert size={16} aria-hidden />}
        <div className="notice-body"><p><b>{t('Found an open copy.')}</b> {facts}. {status}</p>
          {pills}{notAsked}
          <div className="notice-actions">{read === 'text' && <Button variant="outline" size="sm" className="notice-ghost" onClick={() => choose('text')}>{t('Read the plain text')}</Button>}
            <Button variant="outline" size="sm" className="notice-ghost" onClick={() => choose('pdf')}>{t('Open the PDF')}</Button></div></div>
      </div>
    }
    const uncertain = row.access.pdf_candidates.filter(c => c.version_status === 'uncertain' && (c.identity_status === 'doi_verified' || c.identity_status === 'title_verified') && c.provider !== 'europepmc').length
    return <div className="notice answer-notice is-attention find-block" role="status"><TriangleAlert size={16} aria-hidden />
      <div className="notice-body"><p><b>{t('No open copy found.')}</b> {list ? t('Checked {services}.', { services: list }) : t('No service could be asked.')} {uncertain > 0 && t(uncertain === 1 ? '{n} file of uncertain version waits for your check in the Sources panel.' : '{n} files of uncertain version wait for your check in the Sources panel.', { n: uncertain })} {proxy && row.doi && t('The publisher copy may open through your institution.')}</p>
        {pills}{notAsked}
        <div className="notice-actions">{proxy && row.doi && <a className="notice-ghost btn-link" href={proxied(proxy.address, `https://doi.org/${row.doi}`)} target="_blank" rel="noreferrer"><LinkIcon size={14} aria-hidden />{t('Open via {proxy}', { proxy: proxy.label })}</a>}
          {actions && <Button variant="outline" size="sm" className="notice-ghost" disabled={busy} onClick={() => actions.onAttach(row)}><FileUp size={14} aria-hidden />{t('Attach PDF')}</Button>}</div></div>
    </div>
  })()

  const tabs: [Tab, string][] = hasPdf ? [['text', 'Plain text'], ['pdf', 'PDF'], ['abs', 'Abstract']] : [['abs', 'Abstract'], ['text', 'Plain text'], ['pdf', 'PDF']]
  const notesToggle = (doc: AssetText) => doc.passages.some(item => item.text.split(/\n{2,}/).some(p => AUTHOR_NOTE.test(p.trim()))) && <button type="button" className="pdf-text-notes-toggle" onClick={() => setShowNotes(v => !v)}>{t(showNotes ? 'Hide author notes' : 'Show author notes')}</button>
  // "Cited passage i of N" and the size of the text read (mockup `.docnav`, P17).
  const docnav = (doc: AssetText) => <div className="docnav">
    {groups > 0 && <><span>{t('Cited passage {i} of {n}', { i: groupAt + 1, n: groups })}</span>
      <button type="button" className="ib" aria-label={t('Previous passage')} title={t('Previous passage')} disabled={groups < 2} onClick={() => goToGroup(groupAt - 1)}><ChevronLeft size={15} aria-hidden /></button>
      <button type="button" className="ib" aria-label={t('Next passage')} title={t('Next passage')} disabled={groups < 2} onClick={() => goToGroup(groupAt + 1)}><ChevronRight size={15} aria-hidden /></button></>}
    <span className="spacer" />
    <span>{t((doc === shownDocument ? textRendition : doc.asset.rendition) ? 'Text drawn from Europe PMC · {n} pages' : 'Text from the PDF · {n} pages', { n: pages(doc) })}</span>
  </div>
  const empty = (kind: 'text' | 'pdf') => <div className="empty source-empty">
    <div>{kind === 'text' ? <AlignLeft aria-hidden /> : <FileText aria-hidden />}
      <h2>{t(kind === 'text' ? 'No full text yet' : 'No PDF yet')}</h2>
      <p>{kind === 'text'
        ? t(abstractId ? 'DEIXIS has only the abstract of this work. Find an open copy or attach the PDF, and the plain text appears here.' : 'DEIXIS has no text of this work yet. Find an open copy or attach the PDF, and the plain text appears here.')
        : t(pdfUnavailable)}</p>
      {!removed && emptyActions}</div>
  </div>

  const textTab = passage && !abstract
    ? shownDocument !== null ? <>
      {shownDocument && docnav(shownDocument)}
      <h3 className="source-section">{t('Extracted PDF text')}{shownDocument && notesToggle(shownDocument)}</h3>
      {shownDocument ? <PdfTextDocument researchId={researchId} assetId={shownDocument.asset.id} passages={shownDocument.passages} showNotes={showNotes} sourceTitle={shownDocument.source.title} citation={citation} comparison={comparing} suppressFigurePictures={earlier && !comparing} rendition={textRendition} /> : <p>{t('Loading PDF text…')}</p>}
    </> : <>
      <h3 className="source-section">{t('Cited passage · {locator}', { locator: locatorText(passage) })}</h3>
      {expectHighlight && !highlightAvailable && <div className="citation-highlight-note">{citationLabels?.unmarked ?? t('This saved citation has no exact text anchor, so it cannot be highlighted. Generate a new answer to repair its citation anchors.')}</div>}
      <p className="passage-text"><HighlightedPassageText passage={passage} highlightTexts={highlights} markLabel={citationLabels?.mark} /></p>
    </>
    : otherText ? <>
      {otherText.passages.length > 0 && docnav(otherText)}
      <h3 className="source-section">{t('Extracted PDF text')}{notesToggle(otherText)}</h3>
      {otherText.passages.length ? <PdfTextDocument researchId={researchId} assetId={otherText.asset.id} passages={otherText.passages} showNotes={showNotes} sourceTitle={otherText.source.title} rendition={Boolean(otherText.asset.rendition)} /> : <Notice tone="info">{t('No text was extracted from this PDF.')}</Notice>}
    </>
    : needsOtherText ? <p>{t('Loading PDF text…')}</p>
    : empty('text')

  const abstractTab = abstractShown ? <>
    {abstract && !pdfAssetId && <p className="source-notice"><Info size={15} aria-hidden />{t('No PDF is attached, so only the abstract can be inspected. Claims citing this source rest on the abstract alone.')}</p>}
    <h3 className="source-section">{t('Abstract')}</h3>
    {abstract && expectHighlight && !highlightAvailable && <div className="citation-highlight-note">{citationLabels?.unmarked ?? t('This saved citation has no exact text anchor, so it cannot be highlighted. Generate a new answer to repair its citation anchors.')}</div>}
    <p className="passage-text abstract"><HighlightedPassageText passage={abstractShown} highlightTexts={abstract ? highlights : []} markLabel={citationLabels?.mark} /></p>
    {abstract && highlightAvailable && <p className="foot-note">{citationLabels?.marked ?? t('Highlighted: the exact text cited in the answer.')}</p>}
  </> : needsAbstract ? <p>{t('Loading passage…')}</p>
    : <p className="source-notice"><Info size={15} aria-hidden />{t('No abstract is stored for this source.')}</p>

  const content = <>
      <div className="sheet-body source-detail">
        {error && <Notice tone="error">{error}</Notice>}
        {!passage && !assetText && !detailsOnly && !error && <p>{t(openAssetId ? 'Loading PDF text…' : 'Loading passage…')}</p>}
        {(passage || assetText || detailsOnly) && source && <>
          {/* The work (mockup `.dhead`, P12): venue · year · citations, the title, the authors, then its pills. */}
          <div className="dhead">
            {(source.source_key || source.venue || source.year || source.cited_by_count !== null) && <p className="source-venue venue"><SourceKey value={source.source_key} />{[source.venue, source.year, source.cited_by_count !== null ? citedText(source.cited_by_count) : null].filter(Boolean).map((part, i) => <Fragment key={i}>{i > 0 && <span aria-hidden className="source-dot" />}{i === 0 && source.venue ? <i>{part}</i> : <span>{part}</span>}</Fragment>)}</p>}
            <h3 className="source-title">{source.title}</h3>
            {source.authors.length > 0 && <p className="source-byline au">{source.authors.length > 3 && !allAuthors
              ? <>{source.authors.slice(0, 2).join(', ')}, <button className="author-more" onClick={() => setAllAuthors(true)}>{t('and {n} more', { n: source.authors.length - 2 })}</button></>
              : source.authors.join(', ')}</p>}
            <div className="source-chips pills">
              {retractionNote(source) && <span className="ref-pill pill is-retracted" title={retractionNote(source) ?? undefined}>{t('Retracted')}</span>}
              {pdfText === 'text'
                ? <span className="ref-pill pill is-text">{(() => { const doc = shownDocument ?? otherText; const n = doc ? pages(doc) : fileAsset?.page_count ?? null; return n ? t('PDF text · {n} pp.', { n }) : t('PDF text') })()}</span>
                : pdfText === 'none' ? <span className="ref-pill pill is-text">{t('PDF without extracted text')}</span>
                : pdfText === 'pending' ? <span className="ref-pill pill is-text">{t('PDF, text not read yet')}</span>
                : abstractId ? <span className="ref-pill pill is-abstract">{t('Abstract only')}</span>
                : <span className="ref-pill pill">{t('Metadata only')}</span>}
              <span className="ref-pill pill">{source.version_label ? versionText(source.version_label) : t('version not stated by the provider')}</span>
              {source.origin === 'user_upload' && <span className="ref-pill pill">{t('uploaded by you')}</span>}
              {(passage?.text_source === 'ocr' || row?.has_ocr_text) && <span className="ref-pill pill is-ocr warn"><ScanText size={12} aria-hidden />{t(OCR_LABEL)}</span>}
              {passage?.text_source === 'latex_source' && <span className="ref-pill pill is-text"><Sigma size={12} aria-hidden />{t('arXiv source')}</span>}
            </div>
          </div>
          {/* Where the source stands in this research (mockup `.dmeta`, P13): the decision and who made it, the latest
              answer's claims that cite this copy, and the similarity used for ordering. */}
          {row && <p className="dmeta source-role">
            <span className={`is-${row.selection.state}`}>{t(selectionText[row.selection.state])}</span>
            {originText[row.selection.origin] && <span>{t(originText[row.selection.origin]!)}</span>}
            {citedClaims !== null && latestAnswer && <span>{citedClaims ? t(citedClaims === 1 ? 'cited in {n} claim of V{v}' : 'cited in {n} claims of V{v}', { n: citedClaims, v: latestAnswer.version }) : t('not cited in V{v}', { v: latestAnswer.version })}</span>}
            {row.similarity !== null && <span className="tnum" title={t('Used for ordering only; it is not a relevance judgment.')}>{t('similarity {score}', { score: row.similarity.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })}</span>}
          </p>}
          {/* One primary action, then DOI, copy citation and ⋯ (mockup `.dacts`, P14). */}
          <div className="dacts">
            {hasPdf ? <button type="button" className="btn-pri" onClick={() => choose('pdf')}><FileText size={14} aria-hidden />{t('Open PDF')}</button>
              : tab === 'abs' && canFind && <button type="button" className="btn-pri" disabled={busy || finding} onClick={() => { void startFind() }}><Search size={14} aria-hidden />{t('Find PDF')}</button>}
            {doiHref && <a className="ib" href={doiHref} target="_blank" rel="noreferrer" aria-label={t(source.doi ? 'Open DOI' : 'Open publisher page')} title={t(source.doi ? 'Open DOI' : 'Open publisher page')}><LinkIcon size={15} aria-hidden /></a>}
            <button type="button" className="ib" aria-label={t('Copy citation')} title={t('Copy citation')} onClick={copyCitation}><Copy size={15} aria-hidden /></button>
            <DropdownMenu>
              <DropdownMenuTrigger render={<button type="button" className="ib" aria-label={t('More actions')} title={t('More actions')} />}><Ellipsis size={15} aria-hidden /></DropdownMenuTrigger>
              <DropdownMenuContent align="end" sideOffset={6} className="source-more-menu">
                {row && actions && row.version_role !== 'other_version' && (asset
                  ? <DropdownMenuItem disabled={busy} onClick={() => actions.onReplace(row, asset.id)}><Replace size={15} aria-hidden /><span>{t('Replace PDF')}<small>{t('Use another file for this work')}</small></span></DropdownMenuItem>
                  : <DropdownMenuItem disabled={busy} onClick={() => actions.onAttach(row)}><FileUp size={15} aria-hidden /><span>{t('Attach PDF')}<small>{t('From this computer, up to 50 MB')}</small></span></DropdownMenuItem>)}
                {row && actions && !asset && proxy && row.doi && <DropdownMenuItem render={<a href={proxied(proxy.address, `https://doi.org/${row.doi}`)} target="_blank" rel="noreferrer" />}><LinkIcon size={15} aria-hidden /><span>{t('Open via {proxy}', { proxy: proxy.label })}</span></DropdownMenuItem>}
                <DropdownMenuItem onClick={copyBibtex}><Copy size={15} aria-hidden /><span>{t('Copy as BibTeX')}</span></DropdownMenuItem>
                {/* The text tools of the Sources rows (§2.2): extraction again, equations again, OCR. */}
                {row && actions && asset?.current_extraction === false && <DropdownMenuItem className="source-text-tool" disabled={busy} onClick={() => actions.onReextract(row, asset.id)}><ScanText size={15} aria-hidden /><span>{t('Extract text again')}<small>{t('Text extracted as {version}. Extract it again with the current extractor.', { version: asset.extraction_version ?? '?' })}</small></span></DropdownMenuItem>}
                {row && actions && asset?.equations?.state === 'failed' && <DropdownMenuItem className="source-text-tool" disabled={busy} onClick={() => actions.onRereadEquations(row, asset.id)}><Sigma size={15} aria-hidden /><span>{t('Read equations again')}</span></DropdownMenuItem>}
                {row && actions && asset && ocr && ocr.kind !== 'reading' && <DropdownMenuItem className="source-text-tool" disabled={busy || ocr.kind === 'off' || ocr.blocked} onClick={() => actions.ocr.onRead(row, asset.id)}><ScanText size={15} aria-hidden /><span>{t('Read with OCR')}{ocr.kind === 'off' && <small>{ocr.reason}</small>}</span></DropdownMenuItem>}
                {row && actions && <><DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" disabled={busy} onClick={() => actions.onRemove(row)}><Trash2 size={15} aria-hidden /><span>{t('Remove from research')}<small>{t('Moves it to Trash; restore it there')}</small></span></DropdownMenuItem></>}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {findBlock}
          {passage?.removed_from_research && <p className="source-notice is-removed"><ListMinus size={15} aria-hidden /><span>{t('This source was removed from this research. Its passages still open where this research cites them; it is not listed or given to new answers and cells.')}
            {onRestoreSource && <> <button type="button" className="source-notice-action" onClick={() => onRestoreSource(passage.source.id)}><RotateCcw size={13} aria-hidden />{t('Restore to this research')}</button></>}</span></p>}
          {passage && (status === 'pdf_replaced' || status === 'pdf_removed') && <p className="source-notice"><TriangleAlert size={15} aria-hidden />{status === 'pdf_replaced'
            ? t('This passage comes from a PDF that was later replaced. It opens the previous file, which is no longer read in new answers or cells.')
            : t('This passage comes from a PDF that was removed from the source. Its stored text still opens; the PDF view is off.')}</p>}
          {passage?.occurrence && <OccurrenceNotice occurrence={passage.occurrence} earlier={earlier} comparing={comparing} loading={loadingCurrent} onToggle={() => void toggleCurrent()} />}
          {comparisonError && <Notice tone="error">{comparisonError}</Notice>}
          <div className="tab-strip source-view-tabs tabs" role="tablist" aria-label={t('Source view')}>
            {tabs.map(([key, label]) => <button key={key} type="button" role="tab" id={`source-tab-${key}`} aria-selected={tab === key} aria-controls={`source-${key}-view`} className={tab === key ? 'on' : undefined} onClick={() => choose(key)}>{key === 'pdf' ? 'PDF' : t(label)}</button>)}
          </div>
          {tab === 'text' && passage?.text_source === 'marker' && (passage.equations_to_check
            ? <p className="source-notice"><TriangleAlert size={15} aria-hidden />{t(passage.equations_to_check === 1 ? 'Page read from the page image (Marker). {n} equation on this page does not match the PDF’s own text and may be misread; check it against the PDF page.' : 'Page read from the page image (Marker). {n} equations on this page do not match the PDF’s own text and may be misread; check them against the PDF page.', { n: passage.equations_to_check })}</p>
            : <p className="source-notice"><Info size={15} aria-hidden />{t('Page read from the page image (Marker). Equations are LaTeX and tables are rebuilt as tables; check them against the PDF page.')}</p>)}
          {/* The arXiv source route (D104): numbered display equations matched to the page by their numbers, from the
              authors' own LaTeX of this arXiv version. The rest of the passage, including other mathematics, stays the
              PDF's own text layer; the route never checks that the source compiles to this page. */}
          {tab === 'text' && passage?.text_source === 'latex_source' && passage.source_equations?.length ? (
            <p className="source-notice"><Info size={15} aria-hidden />{arxivVersion
              ? t(passage.source_equations.length === 1
                  ? 'Equation ({a}) in this passage is the authors’ LaTeX from the arXiv source (v{version}), matched to the page by its number. The rest of this passage, including other mathematics, is the PDF’s own text.'
                  : 'Equations {numbers} in this passage are the authors’ LaTeX from the arXiv source (v{version}), matched to the page by their numbers. The rest of this passage, including other mathematics, is the PDF’s own text.',
                { a: passage.source_equations[0], version: arxivVersion, numbers: passage.source_equations.map(n => `(${n})`).join(', ') })
              : t(passage.source_equations.length === 1
                  ? 'Equation ({a}) in this passage is the authors’ LaTeX from the arXiv source, matched to the page by its number. The rest of this passage, including other mathematics, is the PDF’s own text.'
                  : 'Equations {numbers} in this passage are the authors’ LaTeX from the arXiv source, matched to the page by their numbers. The rest of this passage, including other mathematics, is the PDF’s own text.',
                { a: passage.source_equations[0], numbers: passage.source_equations.map(n => `(${n})`).join(', ') })}</p>
          ) : null}
          {/* OCR text (D51) is read from the page image and never checked against it; the PDF view opens on the same page. */}
          {tab === 'text' && passage?.text_source === 'ocr' && <p className="source-notice"><TriangleAlert size={15} aria-hidden /><span>{t('This page was read from its scanned image with OCR (Tesseract) on this computer. Letters, numbers and equations may be misread; check them against the PDF page.')}
            {pdfAssetId && <> <button type="button" className="source-notice-action" onClick={() => choose('pdf')}><FileText size={13} aria-hidden />{t('Show this page in the PDF')}</button></>}</span></p>}
          {rendition && <p className="source-notice"><Info size={15} aria-hidden />{t('This PDF was drawn by DEIXIS from Europe PMC’s open-access text. Its pages are not the publisher’s pages.')}</p>}
          {tab === 'abs' && <div id="source-abs-view" role="tabpanel" aria-labelledby="source-tab-abs">{abstractTab}</div>}
          {/* The full-text view's class marks a whole document shown: a cited passage whose document was not the one its
              quote was read from (the identity check above) falls back to the stored passage alone, without it. */}
          {tab === 'text' && <div id="source-text-view" role="tabpanel" aria-labelledby="source-tab-text" className={documentShown ? 'asset-text-view' : undefined} ref={textView}>
            {textTab}
            {passage && !abstract && pdfAssetId && passage.text_source !== 'ocr' && passage.physical_page && <button type="button" className="link source-page-link" onClick={() => choose('pdf')}><FileText size={13} aria-hidden />{t('Show this page in the PDF')}</button>}
          </div>}
          {tab === 'pdf' && <div id="source-pdf-view" role="tabpanel" aria-labelledby="source-tab-pdf" className="source-pdf-view">
            {pdfAssetId ? <>
              {passage && <StoredPdfNotice occurrence={passage.occurrence} />}
              <PdfViewer url={assetUrl(researchId, pdfAssetId)} initialPage={passage?.physical_page ?? initialPage} title={source.title} rendition={pdfRendition} />
            </> : empty('pdf')}
          </div>}
          {/* Where the source came from (mockup `.foot-note`, P20). */}
          {row && (row.provider_records.length > 0 || row.added_at) && <p className="foot-note source-sheet-foot">
            {row.provider_records.length > 0 && <span>{t('Found via')} {row.provider_records.map((id, i) => <Fragment key={id}>{i > 0 && ' · '}{providerName(id)}</Fragment>)}</span>}
            {row.added_at && <span>{t(row.origin === 'user_upload' ? 'Uploaded {date}' : 'Added {date}', { date: new Date(row.added_at).toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short', year: 'numeric' }) })}</span>}
          </p>}
        </>}
      </div>
  </>
  // On the research page the source opens as a side panel (mockup `detail`, P1): the panel's Full width replaces the
  // sheet's expand button, and the PDF view widens the panel as it widened the sheet.
  if (asPanel) return <SourcePanel open={isOpen} full={full} onFull={setFull} dark={dark} description={description} onClose={onClose}>{content}</SourcePanel>
  return <Sheet open={isOpen} onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet source-sheet ${full ? 'is-full' : ''} ${dark ? 'dark' : ''}`}>
      <SheetHeader><SheetTitle><FileText aria-hidden />{t('Source details')}</SheetTitle>
        <Button variant="ghost" size="icon-sm" className="sheet-expand" aria-label={t(full ? 'Collapse panel' : 'Expand to full page')} title={t(full ? 'Collapse panel' : 'Expand to full page')} onClick={() => setFull(v => !v)}>{full ? <Minimize2 /> : <Maximize2 />}</Button><SheetDescription className="sr-only">{description}</SheetDescription></SheetHeader>
      {content}
    </SheetContent>
  </Sheet>
}

function SourcePanel({ open, full, onFull, dark, description, onClose, children }: { open: boolean; full: boolean; onFull: (full: boolean) => void; dark: boolean; description: string; onClose: () => void; children: ReactNode }) {
  const stack = usePanels()
  const setWide = stack?.setWide
  // A request for the full page (the PDF view asks for it) widens the panel once; Full width then belongs to the panel.
  const shown = stack?.current === 'detail'
  useEffect(() => { if (shown && full) { setWide?.(true); onFull(false) } }, [shown, full, setWide, onFull])
  return <StackPanel name="detail" open={open} onClose={onClose} title={t('Source details')} icon={FileText} className={`source-sheet source-panel${dark ? ' dark' : ''}`}>
    <p className="sr-only">{description}</p>
    {children}
  </StackPanel>
}
