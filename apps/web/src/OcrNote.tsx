import { LoaderCircle, ScanText } from 'lucide-react'
import { t } from './i18n'
import { ocrLanguagesText, type OcrOffer } from './ocr'

// One sentence under the source: what OCR would read, why it is off, or how far the run is.
export function OcrNote({ offer }: { offer: OcrOffer }) {
  if (offer.kind === 'reading') {
    const paused = offer.run.status === 'paused'
    const text = offer.total === null ? t(paused ? 'OCR paused' : 'Reading pages without text with OCR…')
      : t(paused ? 'OCR paused · {done} of {total} pages read' : 'Reading with OCR · {done} of {total} pages', { done: offer.done, total: offer.total })
    return <span className="proposal ocr-note" role="status">{paused ? <ScanText size={13} aria-hidden /> : <LoaderCircle size={13} className="chat-spin" aria-hidden />}{text}</span>
  }
  if (offer.kind === 'off') return <span className="proposal ocr-note"><ScanText size={13} aria-hidden />{t('Read with OCR is off: {reason}', { reason: offer.reason })}</span>
  const englishOnly = !offer.tool.languages.includes('tur')
  return <span className="proposal ocr-note"><ScanText size={13} aria-hidden /><span>
    {t(offer.pages === 1 ? '{n} page has no text. OCR reads it on this computer if it is a scanned image ({languages}); blank pages are skipped.' : '{n} pages have no text. OCR reads the scanned ones on this computer ({languages}); blank pages are skipped.', { n: offer.pages, languages: ocrLanguagesText(offer.tool.languages) })}
    {englishOnly && ` ${t('Turkish characters may be wrong. {reason}', { reason: offer.tool.reason ?? '' })}`}
  </span></span>
}

export function OcrButton({ offer, busy, onRead }: { offer: OcrOffer; busy: boolean; onRead: () => void }) {
  if (offer.kind === 'reading') return null
  return <button type="button" disabled={busy || offer.kind === 'off' || offer.blocked} onClick={onRead} title={offer.kind === 'off' ? offer.reason : offer.blocked ? t('Available when the current run ends') : undefined}><ScanText size={14} aria-hidden />{t('Read with OCR')}</button>
}
