import { Button } from '@/components/ui/button'
import { Notice } from '../components/Notice'
import { t } from '../lib/i18n'

export function RetryNotice({ busy, retry }: { busy: boolean; retry: () => void }) {
  return <Notice tone="attention"><p>{t('The last request may or may not have been saved.')}</p><Button type="button" variant="outline" disabled={busy} aria-describedby={busy ? 'review-retry-busy' : undefined} onClick={retry}>{t('Retry')}</Button>{busy && <p id="review-retry-busy" role="status"><span className="shimmer-text">{t('Saving…')}</span></p>}</Notice>
}
