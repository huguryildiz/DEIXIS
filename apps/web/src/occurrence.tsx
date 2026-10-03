import { Button } from '@/components/ui/button'
import type { ExtractionOccurrence } from './api'
import { t } from './i18n'
import { Notice } from './Notice'

export function OccurrenceNotice({ occurrence, earlier, comparing, loading, onToggle }: {
  occurrence: ExtractionOccurrence; earlier: boolean; comparing: boolean; loading: boolean; onToggle: () => void
}) {
  if (!earlier && !occurrence.file_restored_after) return null
  return <Notice tone="attention">
    {earlier && <p>{t('This passage comes from an earlier text extraction ({version}). New answers and cells read the current extraction.', { version: occurrence.extraction_version ?? '?' })}</p>}
    <p>{t(occurrence.input_relation === 'input_matched_expected_hash'
      ? "This text was read from bytes matching the file's recorded hash."
      : occurrence.input_relation === 'input_differed_from_expected_hash'
        ? "This text was read from bytes that differed from the file's recorded hash."
        : 'Which bytes this text was read from was not recorded.')}
      {occurrence.input_relation === 'input_differed_from_expected_hash' && ` ${t(occurrence.retained_copy ? 'Those bytes are kept.' : 'Those bytes were not kept.')}`}</p>
    {occurrence.file_restored_after && <p>{t('The PDF file was restored after this text was extracted.')}</p>}
    {earlier && <Button size="sm" variant="outline" aria-disabled={loading || undefined} onClick={() => { if (!loading) onToggle() }}>{t(comparing ? 'Back to cited text' : 'Show current text')}</Button>}
    {loading && <p role="status">{t('Loading current text…')}</p>}
  </Notice>
}

export function StoredPdfNotice({ occurrence }: { occurrence: ExtractionOccurrence | null }) {
  if (!occurrence || (occurrence.is_current && !occurrence.file_restored_after && occurrence.input_relation === 'input_matched_expected_hash')) return null
  return <Notice tone="info">{t(occurrence.file_restored_after
    ? 'The PDF shown is the stored file, restored after this text was extracted. It is not necessarily the bytes this text was read from.'
    : 'The PDF shown is the stored file. It is not necessarily the bytes this text was read from.')}</Notice>
}
