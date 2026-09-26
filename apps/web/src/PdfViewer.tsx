import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, Minus, Plus } from 'lucide-react'
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { t } from './i18n'
import { scrollBehavior } from './motion'
import { Notice } from './Notice'
import { pageLocator } from './labels'

GlobalWorkerOptions.workerSrc = workerUrl

export function PdfViewer({ url, initialPage = 1, title, rendition = false }: { url: string; initialPage?: number; title: string; rendition?: boolean }) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(initialPage)
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    let disposed = false
    const task = getDocument({ url: url.split('#')[0] })
    task.promise.then(pdf => {
      if (disposed) return
      setDocument(pdf)
      setPage(Math.min(Math.max(initialPage, 1), pdf.numPages))
      setError('')
    }).catch((reason: unknown) => {
      if (!disposed) setError(reason instanceof Error ? reason.message : String(reason))
    })
    return () => {
      disposed = true
      void task.destroy()
    }
  }, [initialPage, url])

  useEffect(() => {
    const node = viewportRef.current
    if (!node) return
    const observer = new ResizeObserver(entries => setWidth(entries[0]?.contentRect.width ?? 0))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!document || !canvasRef.current || width === 0) return
    let cancelled = false
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | null = null
    document.getPage(page).then(pdfPage => {
      if (cancelled || !canvasRef.current) return
      const natural = pdfPage.getViewport({ scale: 1 })
      const fittedScale = Math.max(.25, (width - 40) / natural.width)
      const cssViewport = pdfPage.getViewport({ scale: fittedScale * zoom })
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
      const renderViewport = pdfPage.getViewport({ scale: fittedScale * zoom * pixelRatio })
      const canvas = canvasRef.current
      canvas.width = Math.floor(renderViewport.width)
      canvas.height = Math.floor(renderViewport.height)
      canvas.style.width = `${Math.floor(cssViewport.width)}px`
      canvas.style.height = `${Math.floor(cssViewport.height)}px`
      const context = canvas.getContext('2d')
      if (!context) return
      renderTask = pdfPage.render({ canvas, canvasContext: context, viewport: renderViewport })
      return renderTask.promise
    }).catch(reason => {
      if (!cancelled && (reason as { name?: string }).name !== 'RenderingCancelledException') {
        setError(reason instanceof Error ? reason.message : String(reason))
      }
    })
    return () => {
      cancelled = true
      renderTask?.cancel()
    }
  }, [document, page, width, zoom])

  const changePage = (next: number) => {
    if (!document) return
    setPage(Math.min(Math.max(next, 1), document.numPages))
    viewportRef.current?.scrollTo({ top: 0, behavior: scrollBehavior() })
  }

  return <section className="pdf-viewer" aria-label={`${title} · ${pageLocator(page, rendition)}`}>
    <div className="pdf-toolbar">
      <div className="pdf-page-controls">
        <button type="button" aria-label={t('Previous page')} disabled={!document || page <= 1} onClick={() => changePage(page - 1)}><ChevronLeft /></button>
        <input aria-label={t('Page number')} inputMode="numeric" value={page} onChange={event => changePage(Number(event.target.value) || 1)} />
        <span>/ {document?.numPages ?? '—'}</span>
        <button type="button" aria-label={t('Next page')} disabled={!document || page >= document.numPages} onClick={() => changePage(page + 1)}><ChevronRight /></button>
      </div>
      <div className="pdf-zoom-controls">
        <button type="button" aria-label={t('Zoom out')} disabled={zoom <= .6} onClick={() => setZoom(value => Math.max(.6, value - .1))}><Minus /></button>
        <span>{Math.round(zoom * 100)}%</span>
        <button type="button" aria-label={t('Zoom in')} disabled={zoom >= 2.4} onClick={() => setZoom(value => Math.min(2.4, value + .1))}><Plus /></button>
      </div>
      <a className="pdf-download" href={url.split('#')[0]} download aria-label={t('Download PDF')} title={t('Download PDF')}><Download /></a>
    </div>
    <div className="pdf-document" ref={viewportRef}>
      {error ? <Notice tone="error">{t('Could not display PDF: {message}', { message: error })}</Notice> : !document && <p>{t('Loading PDF…')}</p>}
      <canvas ref={canvasRef} aria-label={pageLocator(page, rendition)} />
    </div>
  </section>
}
