import { Button } from '@/components/ui/button'
import { Notice } from '../Notice'
import { t } from '../i18n'
import type { useFollowUpCommand } from './commands'

export function CommandFeedback({ command }: { command: ReturnType<typeof useFollowUpCommand> }) {
  return <>
    {command.error && <Notice tone="error">{command.error}</Notice>}
    {command.busy && <p role="status">{t('Sending follow-up command…')}</p>}
    {command.pending && !command.busy && <Notice tone="error">{t('The request did not receive an HTTP answer. Retry sends the same command.')} <Button variant="outline" onClick={() => { void command.retry() }}>{t('Retry')}</Button></Notice>}
  </>
}
